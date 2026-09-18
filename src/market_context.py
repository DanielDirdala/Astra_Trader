from src.database import Database


class MarketContext:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

    def _analyze_index(
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

            return {
                "symbol":
                    symbol,

                "available":
                    False,
            }

        rows = list(
            reversed(rows)
        )

        latest = rows[-1]

        price = float(
            latest["close"]
        )

        close_5 = float(
            rows[-6]["close"]
        )

        close_20 = float(
            rows[-21]["close"]
        )

        return {
            "symbol":
                symbol,

            "available":
                True,

            "price":
                price,

            "return_5d":
                (
                    price / close_5
                    - 1
                ) * 100,

            "return_20d":
                (
                    price / close_20
                    - 1
                ) * 100,

            "above_sma20":
                (
                    price
                    > float(
                        latest["sma_20"]
                    )
                    if latest["sma_20"]
                    else None
                ),

            "above_sma50":
                (
                    price
                    > float(
                        latest["sma_50"]
                    )
                    if latest["sma_50"]
                    else None
                ),

            "above_sma200":
                (
                    price
                    > float(
                        latest["sma_200"]
                    )
                    if latest["sma_200"]
                    else None
                ),
        }

    def build(
        self,
    ):

        spy = self._analyze_index(
            "SPY"
        )

        qqq = self._analyze_index(
            "QQQ"
        )

        bullish_signals = 0
        bearish_signals = 0

        for index in (
            spy,
            qqq,
        ):

            for key in (
                "above_sma20",
                "above_sma50",
                "above_sma200",
            ):

                if index.get(key) is True:
                    bullish_signals += 1

                if index.get(key) is False:
                    bearish_signals += 1

        if bullish_signals >= 5:

            regime = "bullish"

        elif bearish_signals >= 5:

            regime = "bearish"

        else:

            regime = "mixed"

        return {
            "market_regime":
                regime,

            "spy":
                spy,

            "qqq":
                qqq,
        }