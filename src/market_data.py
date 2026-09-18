from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pandas as pd

from alpaca.data.enums import DataFeed

from alpaca.data.historical import (
    StockHistoricalDataClient,
)

from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestTradeRequest,
)

from alpaca.data.timeframe import (
    TimeFrame,
)

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
)


class MarketData:

    def __init__(self):

        self.client = (
            StockHistoricalDataClient(
                ALPACA_API_KEY,
                ALPACA_SECRET_KEY,
            )
        )

    def get_daily_bars(
        self,
        symbol: str,
        trading_days: int = 250,
    ) -> pd.DataFrame:

        symbol = symbol.upper()

        calendar_days = int(
            trading_days * 1.8
        )

        end = datetime.now(
            timezone.utc
        )

        start = (
            end
            - timedelta(
                days=calendar_days
            )
        )

        request = StockBarsRequest(
            symbol_or_symbols=[
                symbol
            ],

            timeframe=TimeFrame.Day,

            start=start,
            end=end,

            feed=DataFeed.IEX,
        )

        result = (
            self.client
            .get_stock_bars(
                request
            )
        )

        df = result.df

        if df.empty:
            return df

        if isinstance(
            df.index,
            pd.MultiIndex
        ):

            try:

                df = (
                    df
                    .xs(
                        symbol,
                        level="symbol"
                    )
                    .copy()
                )

            except KeyError:

                return pd.DataFrame()

        return (
            df
            .sort_index()
            .tail(
                trading_days
            )
        )

    def get_latest_price(
        self,
        symbol: str,
    ) -> float:

        symbol = symbol.upper()

        request = StockLatestTradeRequest(
            symbol_or_symbols=[
                symbol
            ],
            feed=DataFeed.IEX,
        )

        result = (
            self.client
            .get_stock_latest_trade(
                request
            )
        )

        return float(
            result[symbol].price
        )