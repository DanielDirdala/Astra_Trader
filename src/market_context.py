from src.database import Database


class MarketContext:

    def __init__(self, database=None):

        self.db = (
            database
            or Database()
        )

    def analyze_index(
        self,
        symbol: str,
    ):

        rows = (
            self.db
            .get_recent_snapshots(
                symbol=symbol,
                limit=25,
            )
        )

        if len(rows) < 21:

            return {
                "symbol": symbol,
                "available": False,
            }

        rows = list(
            reversed(rows)
        )

        latest = rows[-1]

        price = float(
            latest["close"]
        )

        close_5d = float(
            rows[-6]["close"]
        )

        close_20d = float(
            rows[-21]["close"]
        )

        sma20 = latest["sma_20"]
        sma50 = latest["sma_50"]
        sma200 = latest["sma_200"]

        return {
            "symbol":
                symbol,

            "available":
                True,

            "price":
                price,

            "return_5d":
                (
                    price / close_5d
                    - 1
                ) * 100,

            "return_20d":
                (
                    price / close_20d
                    - 1
                ) * 100,

            "rsi_14":
                (
                    float(
                        latest["rsi_14"]
                    )
                    if latest["rsi_14"]
                    is not None
                    else None
                ),

            "atr_14":
                (
                    float(
                        latest["atr_14"]
                    )
                    if latest["atr_14"]
                    is not None
                    else None
                ),

            "above_sma20":
                (
                    price
                    > float(sma20)
                    if sma20 is not None
                    else None
                ),

            "above_sma50":
                (
                    price
                    > float(sma50)
                    if sma50 is not None
                    else None
                ),

            "above_sma200":
                (
                    price
                    > float(sma200)
                    if sma200 is not None
                    else None
                ),
        }

    def determine_regime(
        self,
        spy,
        qqq,
    ):

        bullish = 0
        bearish = 0

        for index in (
            spy,
            qqq,
        ):

            if not index.get(
                "available"
            ):
                continue

            for field in (
                "above_sma20",
                "above_sma50",
                "above_sma200",
            ):

                value = index.get(
                    field
                )

                if value is True:
                    bullish += 1

                elif value is False:
                    bearish += 1

        if bullish >= 5:
            return "bullish"

        if bearish >= 5:
            return "bearish"

        return "mixed"

    def build(self):

        spy = self.analyze_index(
            "SPY"
        )

        qqq = self.analyze_index(
            "QQQ"
        )

        regime = (
            self.determine_regime(
                spy,
                qqq,
            )
        )

        return {
            "market_regime":
                regime,

            "SPY":
                spy,

            "QQQ":
                qqq,
        }