"""Current-market reference levels and WATCH-zone monitoring.

This module does not make or submit orders. It derives deterministic reference
levels from the current Alpaca snapshot plus completed-session indicators, and
can later compare fresh quotes against Astra's saved WATCH zones.
"""
from __future__ import annotations

import math
from typing import Any


def _num(value: Any):
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _positive(value: Any):
    value = _num(value)
    return value if value is not None and value > 0 else None


def _bar(live: dict, name: str) -> dict:
    snapshot = live.get("snapshot") or {}
    value = snapshot.get(name) or {}
    return value if isinstance(value, dict) else {}


def reference_levels(candidate: dict) -> dict:
    """Build non-prescriptive price landmarks for Astra.

    These are observations/reference levels, not buy/sell recommendations.
    Current-session daily-bar fields may be partial.
    """
    q = candidate.get("quantitative") or {}
    live = candidate.get("live_market") or {}
    daily = _bar(live, "dailyBar")
    previous = _bar(live, "prevDailyBar")

    midpoint = _positive(live.get("midpoint"))
    last_trade = _positive(live.get("last_trade"))
    completed_close = _positive(q.get("price"))
    current = midpoint or last_trade or completed_close
    atr = _positive(q.get("atr_14"))

    values = {
        "current_reference_price": current,
        "bid": _positive(live.get("bid")),
        "ask": _positive(live.get("ask")),
        "last_trade": last_trade,
        "completed_session_close": completed_close,
        "sma_20": _positive(q.get("sma_20")),
        "sma_50": _positive(q.get("sma_50")),
        "sma_200": _positive(q.get("sma_200")),
        "completed_20d_high": _positive(q.get("high_20")),
        "completed_20d_low": _positive(q.get("low_20")),
        "atr_14": atr,
        "current_day_open": _positive(daily.get("o")),
        "current_day_high": _positive(daily.get("h")),
        "current_day_low": _positive(daily.get("l")),
        "current_day_vwap": _positive(daily.get("vw")),
        "previous_close": _positive(previous.get("c")),
        "quote_fresh": bool(live.get("quote_fresh")),
        "regular_market_open": bool(live.get("regular_market_open")),
        "quote_timestamp": live.get("quote_timestamp"),
        "quote_age_seconds": _num(live.get("quote_age_seconds")),
        "spread_bps": _num(live.get("spread_bps")),
    }

    if current and atr:
        values.update({
            "current_minus_0_5_atr": current - 0.5 * atr,
            "current_minus_1_0_atr": current - atr,
            "current_plus_0_5_atr": current + 0.5 * atr,
            "current_plus_1_0_atr": current + atr,
        })

    def clean(items):
        return sorted({round(x, 6) for x in items if x is not None and x > 0})

    supports = clean([
        values.get("sma_20"),
        values.get("sma_50"),
        values.get("completed_20d_low"),
        values.get("current_day_low"),
        values.get("current_day_vwap"),
        values.get("previous_close"),
        values.get("current_minus_0_5_atr"),
        values.get("current_minus_1_0_atr"),
    ])
    resistances = clean([
        values.get("completed_20d_high"),
        values.get("current_day_high"),
        values.get("current_plus_0_5_atr"),
        values.get("current_plus_1_0_atr"),
    ])
    values["support_references"] = supports
    values["resistance_references"] = resistances
    values["note"] = (
        "Reference levels only. Current-day OHLC/VWAP may be partial; completed "
        "SMA/ATR/high/low use prior completed sessions."
    )
    return values


def watch_state(evaluation: dict, live: dict) -> dict:
    """Compare a fresh quote with one saved WATCH plan without creating an order."""
    midpoint = _positive(live.get("midpoint"))
    fresh = bool(live.get("quote_fresh"))
    market_open = bool(live.get("regular_market_open"))
    low = _positive(evaluation.get("watch_buy_zone_low"))
    high = _positive(evaluation.get("watch_buy_zone_high"))
    breakout = _positive(evaluation.get("watch_breakout_trigger"))

    state = "NO_MACHINE_TRIGGER"
    if midpoint is None:
        state = "NO_PRICE"
    elif not fresh:
        state = "STALE_QUOTE"
    elif low is not None and high is not None and low <= midpoint <= high:
        state = "BUY_ZONE_PRICE_TRIGGER"
    elif breakout is not None and midpoint >= breakout:
        state = "BREAKOUT_PRICE_TRIGGER"
    elif low is not None and midpoint < low:
        state = "BELOW_BUY_ZONE"
    elif high is not None and midpoint > high:
        state = "ABOVE_BUY_ZONE"

    return {
        "state": state,
        "midpoint": midpoint,
        "quote_fresh": fresh,
        "regular_market_open": market_open,
        "quote_age_seconds": _num(live.get("quote_age_seconds")),
        "bid": _positive(live.get("bid")),
        "ask": _positive(live.get("ask")),
        "watch_buy_zone_low": low,
        "watch_buy_zone_high": high,
        "watch_breakout_trigger": breakout,
        "note": (
            "A price trigger is not a BUY decision. Refresh indicators/news and "
            "perform a new review before constructing an order."
        ),
    }
