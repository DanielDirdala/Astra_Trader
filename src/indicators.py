import numpy as np
import pandas as pd


def calculate_rsi(
    close: pd.Series,
    period: int = 14,
):

    delta = close.diff()

    gains = delta.clip(
        lower=0
    )

    losses = (
        -delta.clip(
            upper=0
        )
    )

    avg_gain = gains.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()

    avg_loss = losses.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan
        )
    )

    return (
        100
        - (
            100
            / (
                1 + rs
            )
        )
    )


def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
):

    previous_close = (
        df["close"]
        .shift(1)
    )

    ranges = pd.concat(
        [
            df["high"]
            - df["low"],

            (
                df["high"]
                - previous_close
            ).abs(),

            (
                df["low"]
                - previous_close
            ).abs(),
        ],
        axis=1,
    )

    true_range = (
        ranges
        .max(axis=1)
    )

    return (
        true_range
        .ewm(
            alpha=1 / period,
            adjust=False,
        )
        .mean()
    )


def add_indicators(
    df: pd.DataFrame,
):

    if df.empty:
        return df

    df = df.copy()

    # Moving averages

    df["sma_20"] = (
        df["close"]
        .rolling(20)
        .mean()
    )

    df["sma_50"] = (
        df["close"]
        .rolling(50)
        .mean()
    )

    df["sma_200"] = (
        df["close"]
        .rolling(200)
        .mean()
    )

    df["ema_8"] = (
        df["close"]
        .ewm(
            span=8,
            adjust=False,
        )
        .mean()
    )

    df["ema_21"] = (
        df["close"]
        .ewm(
            span=21,
            adjust=False,
        )
        .mean()
    )

    df["ema_50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False,
        )
        .mean()
    )

    # RSI

    df["rsi_14"] = calculate_rsi(
        df["close"]
    )

    # ATR

    df["atr_14"] = calculate_atr(
        df
    )

    # MACD

    ema_12 = (
        df["close"]
        .ewm(
            span=12,
            adjust=False
        )
        .mean()
    )

    ema_26 = (
        df["close"]
        .ewm(
            span=26,
            adjust=False
        )
        .mean()
    )

    df["macd"] = (
        ema_12
        - ema_26
    )

    df["macd_signal"] = (
        df["macd"]
        .ewm(
            span=9,
            adjust=False,
        )
        .mean()
    )

    df["macd_histogram"] = (
        df["macd"]
        - df["macd_signal"]
    )

    # Volume

    df["avg_volume_20"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"]
        / df["avg_volume_20"]
    )

    # Range

    df["high_20"] = (
        df["high"]
        .rolling(20)
        .max()
    )

    df["low_20"] = (
        df["low"]
        .rolling(20)
        .min()
    )

    # Distance from MAs

    for period in (
        20,
        50,
        200,
    ):

        df[
            f"distance_sma_{period}_pct"
        ] = (
            (
                df["close"]
                - df[
                    f"sma_{period}"
                ]
            )
            / df[
                f"sma_{period}"
            ]
            * 100
        )

    return df