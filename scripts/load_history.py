import argparse
import math

import pandas as pd

from src.database import Database
from src.indicators import add_indicators
from src.market_data import MarketData
from src.universe import get_universe

from config import HISTORY_DAYS


def clean_number(
    value,
):

    if value is None:
        return None

    try:

        number = float(
            value
        )

        if (
            math.isnan(number)
            or math.isinf(number)
        ):

            return None

        return number

    except (
        ValueError,
        TypeError,
    ):

        return None


def clean_integer(
    value,
):

    if value is None:
        return None

    if pd.isna(value):
        return None

    return int(
        value
    )


def convert_row(
    row,
):

    keys = [
        "open",
        "high",
        "low",
        "close",

        "vwap",

        "sma_20",
        "sma_50",
        "sma_200",

        "ema_8",
        "ema_21",
        "ema_50",

        "rsi_14",
        "atr_14",

        "macd",
        "macd_signal",
        "macd_histogram",

        "avg_volume_20",
        "volume_ratio",

        "high_20",
        "low_20",

        "distance_sma_20_pct",
        "distance_sma_50_pct",
        "distance_sma_200_pct",
    ]

    data = {
        key:
            clean_number(
                row.get(key)
            )
        for key
        in keys
    }

    data["volume"] = (
        clean_integer(
            row.get("volume")
        )
    )

    data["trade_count"] = (
        clean_integer(
            row.get(
                "trade_count"
            )
        )
    )

    data["raw_data"] = {
        key: value
        for key, value
        in data.items()
        if value is not None
    }

    return data


def load_symbol(
    symbol,
    days,
    market,
    database,
):

    print(
        f"Downloading {symbol}..."
    )

    df = (
        market
        .get_daily_bars(
            symbol,
            trading_days=days,
        )
    )

    if df.empty:

        print(
            f"{symbol}: no data."
        )

        return False

    df = add_indicators(
        df
    )

    for timestamp, row in (
        df.iterrows()
    ):

        database.save_market_snapshot(
            symbol=
                symbol,

            timestamp=
                timestamp,

            timeframe=
                "1Day",

            data=
                convert_row(
                    row
                ),
        )

    print(
        f"{symbol}: "
        f"{len(df)} snapshots saved."
    )

    return True


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols. "
            "Default uses universe.py."
        ),
    )

    parser.add_argument(
        "--days",
        type=int,
        default=HISTORY_DAYS,
    )

    args = parser.parse_args()

    if args.symbols:

        symbols = [
            value.strip().upper()
            for value
            in args.symbols.split(",")
        ]

    else:

        symbols = (
            get_universe()
        )

    market = MarketData()
    database = Database()

    success = 0
    failed = 0

    print()
    print(
        "ASTRA HISTORICAL DATA LOADER"
    )
    print(
        "============================"
    )

    for symbol in symbols:

        try:

            if load_symbol(
                symbol,
                args.days,
                market,
                database,
            ):

                success += 1

        except Exception as error:

            failed += 1

            print(
                f"ERROR {symbol}: "
                f"{error}"
            )

            database.log_event(
                "MARKET_DATA_ERROR",

                symbol=
                    symbol,

                message=
                    str(error),
            )

    print()
    print(
        "============================"
    )

    print(
        f"Successful symbols: "
        f"{success}"
    )

    print(
        f"Failed symbols:     "
        f"{failed}"
    )


if __name__ == "__main__":
    main()