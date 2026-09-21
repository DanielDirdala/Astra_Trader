"""Deterministic quality/event screening before an Astra finalist review.

This module does not make a trading decision. It converts already-captured daily
features/news into a compact quality profile, flags obvious special situations,
and lets the paid model see cleaner finalists. News heuristics are deliberately
conservative and incomplete; they are not a substitute for a corporate-actions
or earnings-calendar data source.
"""
from __future__ import annotations

import re
from copy import deepcopy

from src.us_market_ops import number


HARD_EVENT_PATTERNS = {
    'M_AND_A_PENDING': (
        r'\bdefinitive agreement\b.*\bacquir',
        r'\bto acquire\b',
        r'\bwill acquire\b',
        r'\bmerger agreement\b',
        r'\btender offer\b',
        r'\btake[- ]private\b',
        r'\bgoing private\b',
    ),
    'BANKRUPTCY_OR_DELISTING': (
        r'\bchapter 11\b',
        r'\bbankruptcy\b',
        r'\bdelist(?:ing|ed)?\b',
    ),
}

SOFT_EVENT_PATTERNS = {
    'REVERSE_SPLIT': (r'\breverse stock split\b', r'\breverse split\b'),
    'EQUITY_OFFERING': (
        r'\bpublic offering\b', r'\bregistered direct offering\b',
        r'\bat-the-market offering\b', r'\bequity offering\b',
    ),
    'CRYPTO_TREASURY_EXPOSURE': (
        r'\bbitcoin treasury\b', r'\bBTC treasury\b', r'\bcrypto treasury\b',
    ),
}


def _text(candidate):
    parts = []
    for item in candidate.get('recent_news') or []:
        parts.append(str(item.get('headline') or ''))
        parts.append(str(item.get('summary') or ''))
    return ' '.join(parts)


def _matched_labels(text, mapping):
    hits = []
    for label, patterns in mapping.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            hits.append(label)
    return hits


def _between(value, low, high):
    value = number(value)
    return value is not None and low <= value <= high


def setup_profile(candidate):
    """Return a long-swing setup profile from existing completed-daily indicators."""
    q = candidate.get('quantitative') or {}
    price = number(q.get('price'))
    sma20 = number(q.get('sma_20'))
    sma50 = number(q.get('sma_50'))
    sma200 = number(q.get('sma_200'))
    high20 = number(q.get('high_20'))
    rsi = number(q.get('rsi_14'))
    atr_pct = number(q.get('atr_pct'))
    vol_ratio = number(q.get('volume_ratio'))
    rs_spy = number(q.get('relative_strength_spy'))
    rs_qqq = number(q.get('relative_strength_qqq'))
    momentum = number(q.get('momentum_score'))
    ret20 = number(q.get('return_20d'))
    macd_hist = number(q.get('macd_histogram'))
    max_day = number(q.get('max_abs_daily_return_20d_pct'))

    flags = {
        'above_sma20': bool(price and sma20 and price > sma20),
        'above_sma50': bool(price and sma50 and price > sma50),
        'above_sma200': bool(price and sma200 and price > sma200),
        'positive_rs_spy': bool(rs_spy is not None and rs_spy > 0),
        'positive_rs_qqq': bool(rs_qqq is not None and rs_qqq > 0),
        'positive_momentum': bool(momentum is not None and momentum > 0),
        'positive_20d_return': bool(ret20 is not None and ret20 > 0),
        'positive_macd_histogram': bool(macd_hist is not None and macd_hist > 0),
        'rsi_swing_zone': _between(rsi, 40, 72),
        'tradable_atr_zone': _between(atr_pct, 0.5, 10.0),
        'volume_not_dormant': bool(vol_ratio is not None and vol_ratio >= 0.6),
        'no_extreme_20d_daily_gap': bool(max_day is None or max_day <= 25.0),
    }

    score = 0
    weights = {
        'above_sma20': 10,
        'above_sma50': 15,
        'above_sma200': 15,
        'positive_rs_spy': 15,
        'positive_rs_qqq': 5,
        'positive_momentum': 10,
        'positive_20d_return': 5,
        'positive_macd_histogram': 10,
        'rsi_swing_zone': 5,
        'tradable_atr_zone': 5,
        'volume_not_dormant': 3,
        'no_extreme_20d_daily_gap': 2,
    }
    for key, weight in weights.items():
        if flags[key]:
            score += weight

    setup = 'UNCLASSIFIED'
    if price and sma20 and sma50 and sma200 and price > sma20 > sma50 > sma200 and flags['positive_rs_spy']:
        setup = 'TREND_CONTINUATION'
    elif price and sma20 and sma50 and sma200 and price > sma50 > sma200 and price <= sma20 * 1.03 and flags['positive_rs_spy'] and _between(rsi, 35, 68):
        setup = 'PULLBACK_IN_UPTREND'
    elif price and high20 and price >= high20 * 0.98 and flags['positive_rs_spy'] and (vol_ratio or 0) >= 0.9:
        setup = 'BREAKOUT_PRESSURE'

    return {
        'setup_type': setup,
        'setup_score': score,
        'flags': flags,
    }


def analyze_candidate(candidate):
    """Return a copy enriched with deterministic event/setup quality metadata."""
    item = deepcopy(candidate)
    text = _text(candidate)
    hard_events = _matched_labels(text, HARD_EVENT_PATTERNS)
    soft_events = _matched_labels(text, SOFT_EVENT_PATTERNS)
    setup = setup_profile(candidate)

    technical = number((candidate.get('quantitative') or {}).get('technical_score')) or 0.0
    penalty = 0.0
    if 'CRYPTO_TREASURY_EXPOSURE' in soft_events:
        penalty += 4.0
    if 'REVERSE_SPLIT' in soft_events:
        penalty += 4.0
    if 'EQUITY_OFFERING' in soft_events:
        penalty += 2.0
    rank_score = technical + setup['setup_score'] / 10.0 - penalty

    profile = {
        **setup,
        'hard_event_flags': hard_events,
        'soft_event_flags': soft_events,
        'event_screen_note': (
            'Headline/summary heuristic only; corporate-actions and earnings calendars remain incomplete.'
        ),
        'finalist_rank_score': round(rank_score, 6),
    }
    item['quality_profile'] = profile
    return item


def exclusion_reason(candidate, min_setup_score=50):
    profile = candidate.get('quality_profile') or setup_profile(candidate)
    hard = profile.get('hard_event_flags') or []
    if hard:
        return 'Special situation excluded from ordinary long-swing ranking: ' + ', '.join(hard)
    if profile.get('setup_type') == 'UNCLASSIFIED':
        return 'No supported trend/pullback/breakout setup classification.'
    if int(profile.get('setup_score') or 0) < int(min_setup_score):
        return f"Setup quality {profile.get('setup_score')} is below minimum {int(min_setup_score)}."
    return None
