import math

import numpy as np
import pandas as pd

from src.database import Database
from src.indicators import add_indicators
from src.market_data import MarketData


SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "SPY",
    "QQQ",
]

TRADING_DAYS = 250


def clean_number(value):

    if value is None:
        return None

    try:

        value = float(value)

        if (
            math.isnan(value)
            or math.isinf(value)
        ):
            return None

        return value

    except (
        TypeError,
        ValueError,
    ):

        return None


def clean_integer(value):

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

        return int(value)

    except (
        TypeError,
        ValueError,
    ):

        return None


def row_to_dictionary(row):

    return {

        "open":
            clean_number(
                row.get("open")
            ),

        "high":
            clean_number(
                row.get("high")
            ),

        "low":
            clean_number(
                row.get("low")
            ),

        "close":
            clean_number(
                row.get("close")
            ),

        "volume":
            clean_integer(
                row.get("volume")
            ),

        "trade_count":
            clean_integer(
                row.get("trade_count")
            ),

        "vwap":
            clean_number(
                row.get("vwap")
            ),

        "sma_20":
            clean_number(
                row.get("sma_20")
            ),

        "sma_50":
            clean_number(
                row.get("sma_50")
            ),

        "sma_200":
            clean_number(
                row.get("sma_200")
            ),

        "ema_8":
            clean_number(
                row.get("ema_8")
            ),

        "ema_21":
            clean_number(
                row.get("ema_21")
            ),

        "ema_50":
            clean_number(
                row.get("ema_50")
            ),

        "rsi_14":
            clean_number(
                row.get("rsi_14")
            ),

        "atr_14":
            clean_number(
                row.get("atr_14")
            ),

        "macd":
            clean_number(
                row.get("macd")
            ),

        "macd_signal":
            clean_number(
                row.get("macd_signal")
            ),

        "macd_histogram":
            clean_number(
                row.get(
                    "macd_histogram"
                )
            ),

        "avg_volume_20":
            clean_number(
                row.get(
                    "avg_volume_20"
                )
            ),

        "volume_ratio":
            clean_number(
                row.get(
                    "volume_ratio"
                )
            ),

        "high_20":
            clean_number(
                row.get("high_20")
            ),

        "low_20":
            clean_number(
                row.get("low_20")
            ),

        "distance_sma_20_pct":
            clean_number(
                row.get(
                    "distance_sma_20_pct"
                )
            ),

        "distance_sma_50_pct":
            clean_number(
                row.get(
                    "distance_sma_50_pct"
                )
            ),

        "distance_sma_200_pct":
            clean_number(
                row.get(
                    "distance_sma_200_pct"
                )
            ),
    }


def load_symbol(
    symbol,
    market,
    database,
):

    print()
    print(
        f"Downloading {symbol}..."
    )

    df = market.get_daily_bars(
        symbol,
        trading_days=TRADING_DAYS,
    )

    if df.empty:

        print(
            f"No data returned for "
            f"{symbol}."
        )

        return

    df = add_indicators(
        df
    )

    inserted = 0

    for timestamp, row in df.iterrows():

        data = row_to_dictionary(
            row
        )

        data["raw_data"] = {
            key: value
            for key, value
            in data.items()
            if value is not None
        }

        database.save_market_snapshot(
            symbol=symbol,

            timestamp=timestamp,

            timeframe="1Day",

            data=data,
        )

        inserted += 1

    print(
        f"{symbol}: "
        f"{inserted} daily snapshots saved."
    )


def main():

    print()
    print("==============================")
    print("ASTRA HISTORICAL DATA LOADER")
    print("==============================")

    market = MarketData()

    database = Database()

    database.log_event(
        event_type="HISTORY_LOAD_STARTED",

        message=(
            "Historical market data "
            "loading started."
        ),

        metadata={
            "symbols": SYMBOLS,
            "days": TRADING_DAYS,
        },
    )

    for symbol in SYMBOLS:

        try:

            load_symbol(
                symbol,
                market,
                database,
            )

        except Exception as error:

            print()
            print(
                f"ERROR loading "
                f"{symbol}: {error}"
            )

            database.log_event(
                event_type=(
                    "MARKET_DATA_ERROR"
                ),

                symbol=symbol,

                message=str(
                    error
                ),
            )

    database.log_event(
        event_type="HISTORY_LOAD_FINISHED",

        message=(
            "Historical market data "
            "loading completed."
        ),
    )

    print()
    print("==============================")
    print("LOAD COMPLETE")
    print("==============================")


if __name__ == "__main__":
    main()