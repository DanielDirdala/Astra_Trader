from uuid import uuid4

from src.database import Database

from config import (
    MIN_PRICE,
    MIN_AVG_VOLUME,
)

from src.universe import (
    get_stock_universe,
)


def pct_change(
    current,
    previous,
):

    if not previous:
        return None

    return (
        (
            current
            - previous
        )
        / previous
        * 100
    )


class Scanner:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

    def _benchmark_returns(
        self,
        symbol,
    ):

        rows = (
            self.db
            .get_recent_snapshots(
                symbol,
                25
            )
        )

        if len(rows) < 21:
            return None

        rows = list(
            reversed(rows)
        )

        latest = float(
            rows[-1]["close"]
        )

        return {
            "return_5d":
                pct_change(
                    latest,
                    float(
                        rows[-6]["close"]
                    )
                ),

            "return_20d":
                pct_change(
                    latest,
                    float(
                        rows[-21]["close"]
                    )
                ),
        }

    def analyze_symbol(
        self,
        symbol,
        spy_returns,
        qqq_returns,
    ):

        rows = (
            self.db
            .get_recent_snapshots(
                symbol,
                250
            )
        )

        if len(rows) < 21:
            return None

        rows = list(
            reversed(rows)
        )

        latest = rows[-1]

        price = float(
            latest["close"]
        )

        avg_volume = (
            float(
                latest[
                    "avg_volume_20"
                ]
            )
            if latest[
                "avg_volume_20"
            ] is not None
            else 0
        )

        if price < MIN_PRICE:
            return None

        if avg_volume < MIN_AVG_VOLUME:
            return None

        return_1d = pct_change(
            price,
            float(
                rows[-2]["close"]
            )
        )

        return_5d = pct_change(
            price,
            float(
                rows[-6]["close"]
            )
        )

        return_20d = pct_change(
            price,
            float(
                rows[-21]["close"]
            )
        )

        atr = (
            float(
                latest["atr_14"]
            )
            if latest["atr_14"]
            else 0
        )

        atr_pct = (
            atr
            / price
            * 100
            if price
            else 0
        )

        rsi = (
            float(
                latest["rsi_14"]
            )
            if latest["rsi_14"]
            else None
        )

        volume_ratio = (
            float(
                latest[
                    "volume_ratio"
                ]
            )
            if latest[
                "volume_ratio"
            ]
            else 0
        )

        rs_spy = (
            return_20d
            - spy_returns[
                "return_20d"
            ]
        )

        rs_qqq = (
            return_20d
            - qqq_returns[
                "return_20d"
            ]
        )

        # ----------------------------------------------
        # Screening scores only.
        # These DO NOT make trading decisions.
        # ----------------------------------------------

        momentum_score = (
            return_5d * 0.35
            + return_20d * 0.45
            + rs_spy * 0.10
            + rs_qqq * 0.10
        )

        trend_bonus = 0

        sma20 = latest["sma_20"]
        sma50 = latest["sma_50"]
        sma200 = latest["sma_200"]

        if (
            sma20
            and price
            > float(sma20)
        ):
            trend_bonus += 2

        if (
            sma50
            and price
            > float(sma50)
        ):
            trend_bonus += 2

        if (
            sma200
            and price
            > float(sma200)
        ):
            trend_bonus += 2

        technical_score = (
            momentum_score
            + trend_bonus
            + min(
                volume_ratio,
                3
            )
        )

        return {
            "symbol":
                symbol,

            "price":
                price,

            "return_1d":
                return_1d,

            "return_5d":
                return_5d,

            "return_20d":
                return_20d,

            "rsi_14":
                rsi,

            "atr_pct":
                atr_pct,

            "volume_ratio":
                volume_ratio,

            "relative_strength_spy":
                rs_spy,

            "relative_strength_qqq":
                rs_qqq,

            "momentum_score":
                momentum_score,

            "technical_score":
                technical_score,

            "metadata": {
                "sma_20":
                    float(sma20)
                    if sma20
                    else None,

                "sma_50":
                    float(sma50)
                    if sma50
                    else None,

                "sma_200":
                    float(sma200)
                    if sma200
                    else None,

                "macd":
                    (
                        float(
                            latest["macd"]
                        )
                        if latest["macd"]
                        else None
                    ),

                "macd_histogram":
                    (
                        float(
                            latest[
                                "macd_histogram"
                            ]
                        )
                        if latest[
                            "macd_histogram"
                        ]
                        else None
                    ),

                "high_20":
                    (
                        float(
                            latest["high_20"]
                        )
                        if latest["high_20"]
                        else None
                    ),
            },
        }

    def run(
        self,
    ):

        scan_id = uuid4()

        spy = self._benchmark_returns(
            "SPY"
        )

        qqq = self._benchmark_returns(
            "QQQ"
        )

        if not spy or not qqq:

            raise RuntimeError(
                "SPY and QQQ history must "
                "exist before scanning."
            )

        results = []

        loaded = set(
            self.db
            .get_loaded_symbols()
        )

        for symbol in (
            get_stock_universe()
        ):

            if symbol not in loaded:
                continue

            result = (
                self.analyze_symbol(
                    symbol,
                    spy,
                    qqq,
                )
            )

            if result is None:
                continue

            result[
                "scan_id"
            ] = scan_id

            self.db.save_scan_result(
                result
            )

            results.append(
                result
            )

        results.sort(
            key=lambda x:
                x["technical_score"],
            reverse=True,
        )

        self.db.log_event(
            "SCAN_COMPLETED",

            message=(
                f"Scanner evaluated "
                f"{len(results)} symbols."
            ),

            metadata={
                "scan_id":
                    str(scan_id)
            }
        )

        return (
            scan_id,
            results
        )