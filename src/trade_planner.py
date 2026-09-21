"""Validated position sizing for Astra research proposals.

Astra proposes entry/stop/target, risk tier, and a share count. Python independently
caps the share count by stop risk, per-position exposure, and portfolio risk/exposure.
No order is submitted here and no live-account integration exists.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_FLOOR


def _dec(value, *, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not a valid numeric value.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'Invalid numeric value: {value!r}') from None
    if not result.is_finite():
        raise ValueError('Numeric value must be finite.')
    return result


def _pct(value, name, low, high):
    value = _dec(value)
    if not Decimal(str(low)) <= value <= Decimal(str(high)):
        raise ValueError(f'{name} must be between {low} and {high}.')
    return value


@dataclass(frozen=True)
class SizingPolicy:
    strategy_capital_usd: Decimal | None = None
    low_risk_pct: Decimal = Decimal('0.25')
    medium_risk_pct: Decimal = Decimal('0.50')
    high_risk_pct: Decimal = Decimal('0.75')
    max_position_pct: Decimal = Decimal('25.0')
    max_total_exposure_pct: Decimal = Decimal('60.0')
    max_total_risk_pct: Decimal = Decimal('1.50')
    min_reward_risk: Decimal = Decimal('1.50')
    min_stop_atr_multiple: Decimal = Decimal('0.50')
    max_stop_atr_multiple: Decimal = Decimal('3.50')

    def __post_init__(self):
        if self.strategy_capital_usd is not None:
            capital = _dec(self.strategy_capital_usd)
            if capital <= 0 or capital > Decimal('100000000'):
                raise ValueError('strategy_capital_usd must be greater than 0 and <= $100,000,000.')
        for name in ('low_risk_pct', 'medium_risk_pct', 'high_risk_pct'):
            _pct(getattr(self, name), name, 0.01, 5.0)
        if not self.low_risk_pct <= self.medium_risk_pct <= self.high_risk_pct:
            raise ValueError('Risk tiers must be ordered low <= medium <= high.')
        _pct(self.max_position_pct, 'max_position_pct', 1, 100)
        _pct(self.max_total_exposure_pct, 'max_total_exposure_pct', 1, 100)
        _pct(self.max_total_risk_pct, 'max_total_risk_pct', 0.05, 10)
        if self.max_total_risk_pct < self.low_risk_pct:
            raise ValueError('max_total_risk_pct is below the low risk tier.')
        if _dec(self.min_reward_risk) < Decimal('0.5'):
            raise ValueError('min_reward_risk must be at least 0.5.')
        if _dec(self.min_stop_atr_multiple) <= 0 or _dec(self.max_stop_atr_multiple) <= self.min_stop_atr_multiple:
            raise ValueError('Invalid ATR stop-multiple bounds.')

    @classmethod
    def load(cls, capital_override=None):
        raw_capital = capital_override if capital_override is not None else os.getenv('ASTRA_STRATEGY_CAPITAL_USD', '').strip()
        capital = None if raw_capital in (None, '') else _dec(raw_capital)
        return cls(
            strategy_capital_usd=capital,
            low_risk_pct=_dec(os.getenv('ASTRA_RISK_LOW_PCT', '0.25')),
            medium_risk_pct=_dec(os.getenv('ASTRA_RISK_MEDIUM_PCT', '0.50')),
            high_risk_pct=_dec(os.getenv('ASTRA_RISK_HIGH_PCT', '0.75')),
            max_position_pct=_dec(os.getenv('ASTRA_MAX_POSITION_PCT', '25.0')),
            max_total_exposure_pct=_dec(os.getenv('ASTRA_MAX_TOTAL_EXPOSURE_PCT', '60.0')),
            max_total_risk_pct=_dec(os.getenv('ASTRA_MAX_TOTAL_RISK_PCT', '1.50')),
            min_reward_risk=_dec(os.getenv('ASTRA_MIN_REWARD_RISK', '1.50')),
            min_stop_atr_multiple=_dec(os.getenv('ASTRA_MIN_STOP_ATR_MULTIPLE', '0.50')),
            max_stop_atr_multiple=_dec(os.getenv('ASTRA_MAX_STOP_ATR_MULTIPLE', '3.50')),
        )

    @classmethod
    def from_payload(cls, payload):
        payload = payload or {}
        tiers = payload.get('risk_tiers_pct_of_capital') or {}
        stop_range = payload.get('stop_distance_atr_multiple_range') or [0.50, 3.50]
        return cls(
            strategy_capital_usd=_dec(payload.get('strategy_capital_usd'), allow_none=True),
            low_risk_pct=_dec(tiers.get('low', 0.25)),
            medium_risk_pct=_dec(tiers.get('medium', 0.50)),
            high_risk_pct=_dec(tiers.get('high', 0.75)),
            max_position_pct=_dec(payload.get('max_position_pct_of_capital', 25.0)),
            max_total_exposure_pct=_dec(payload.get('max_total_exposure_pct_of_capital', 60.0)),
            max_total_risk_pct=_dec(payload.get('max_total_open_risk_pct_of_capital', 1.50)),
            min_reward_risk=_dec(payload.get('min_reward_risk', 1.50)),
            min_stop_atr_multiple=_dec(stop_range[0]),
            max_stop_atr_multiple=_dec(stop_range[1]),
        )

    def with_capital(self, capital):
        return replace(self, strategy_capital_usd=_dec(capital))

    def tier_pct(self, tier):
        table = {'low': self.low_risk_pct, 'medium': self.medium_risk_pct, 'high': self.high_risk_pct}
        if tier not in table:
            raise ValueError('BUY proposal is missing a valid low/medium/high risk tier.')
        return table[tier]

    def model_payload(self):
        return {
            'strategy_capital_usd': float(self.strategy_capital_usd) if self.strategy_capital_usd is not None else None,
            'risk_tiers_pct_of_capital': {
                'low': float(self.low_risk_pct),
                'medium': float(self.medium_risk_pct),
                'high': float(self.high_risk_pct),
            },
            'max_position_pct_of_capital': float(self.max_position_pct),
            'max_total_exposure_pct_of_capital': float(self.max_total_exposure_pct),
            'max_total_open_risk_pct_of_capital': float(self.max_total_risk_pct),
            'min_reward_risk': float(self.min_reward_risk),
            'stop_distance_atr_multiple_range': [float(self.min_stop_atr_multiple), float(self.max_stop_atr_multiple)],
            'sizing_note': 'Astra proposes quantity; Python safety-caps it from entry-stop risk and portfolio limits.',
        }


def _value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _candidate_map(payload):
    return {c['symbol']: c for c in payload.get('candidates') or []}


def validate_buy_geometry(evaluation, candidate, policy: SizingPolicy):
    entry = _dec(_value(evaluation, 'entry_price'))
    stop = _dec(_value(evaluation, 'stop_price'))
    target = _dec(_value(evaluation, 'target_price'))
    if not Decimal('1') <= stop < entry < target:
        raise ValueError('BUY prices must satisfy $1 <= stop < entry < target.')
    risk = entry - stop
    reward = target - entry
    rr = reward / risk
    if rr < policy.min_reward_risk:
        raise ValueError(f'Reward/risk {rr:.2f} is below minimum {policy.min_reward_risk}.')
    q = candidate.get('quantitative') or {}
    atr = _dec(q.get('atr_14'), allow_none=True)
    atr_multiple = None
    if atr is not None and atr > 0:
        atr_multiple = risk / atr
        if not policy.min_stop_atr_multiple <= atr_multiple <= policy.max_stop_atr_multiple:
            raise ValueError(
                f'Stop distance is {atr_multiple:.2f} ATR; allowed range is '
                f'{policy.min_stop_atr_multiple}-{policy.max_stop_atr_multiple} ATR.'
            )
    return {
        'entry': entry, 'stop': stop, 'target': target,
        'risk_per_share': risk, 'reward_per_share': reward,
        'reward_risk': rr, 'stop_atr_multiple': atr_multiple,
    }


def build_trade_plans(report, payload, policy: SizingPolicy):
    """Return validated BUY plans in Astra preference order.

    If strategy capital is absent, geometry/exit plans are still validated but no
    whole-share quantity is authorized.
    """
    candidates = _candidate_map(payload)
    evaluations = {_value(e, 'symbol'): e for e in _value(report, 'evaluations', [])}
    selected = list(_value(report, 'selected_symbols', []) or [])
    plans = []
    capital = policy.strategy_capital_usd
    remaining_exposure = None if capital is None else capital * policy.max_total_exposure_pct / Decimal('100')
    remaining_risk = None if capital is None else capital * policy.max_total_risk_pct / Decimal('100')

    for symbol in selected:
        ev = evaluations.get(symbol)
        candidate = candidates.get(symbol)
        if ev is None or candidate is None or _value(ev, 'decision') != 'BUY':
            continue
        plan = {
            'symbol': symbol,
            'valid': False,
            'validation_error': None,
            'astra_suggested_quantity': _value(ev, 'suggested_quantity'),
            'validated_quantity': None,
            'risk_tier': _value(ev, 'risk_tier'),
            'exit_rule': _value(ev, 'exit_rule') or '',
            'time_stop_days': _value(ev, 'time_stop_days'),
        }
        try:
            geometry = validate_buy_geometry(ev, candidate, policy)
            plan.update({k: float(v) if isinstance(v, Decimal) else v for k, v in geometry.items()})
            plan['valid'] = True
            tier_pct = policy.tier_pct(_value(ev, 'risk_tier'))
            plan['risk_budget_pct'] = float(tier_pct)
            if capital is None:
                plan['sizing_note'] = 'Set ASTRA_STRATEGY_CAPITAL_USD or pass --capital to calculate whole shares.'
                plans.append(plan)
                continue

            per_trade_risk = capital * tier_pct / Decimal('100')
            per_position_notional = capital * policy.max_position_pct / Decimal('100')
            risk_per_share = geometry['risk_per_share']
            entry = geometry['entry']
            by_risk = int((per_trade_risk / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
            by_position = int((per_position_notional / entry).to_integral_value(rounding=ROUND_FLOOR))
            by_portfolio_risk = int((remaining_risk / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
            by_portfolio_exposure = int((remaining_exposure / entry).to_integral_value(rounding=ROUND_FLOOR))
            safe_max = max(0, min(by_risk, by_position, by_portfolio_risk, by_portfolio_exposure))

            astra_qty = _value(ev, 'suggested_quantity')
            if isinstance(astra_qty, bool) or astra_qty is None:
                astra_qty = safe_max
            else:
                astra_qty = int(astra_qty)
            if astra_qty < 1:
                raise ValueError('Astra suggested quantity must be at least 1 for a BUY when strategy capital is configured.')
            qty = min(astra_qty, safe_max)
            if qty < 1:
                raise ValueError('Configured capital/risk limits do not permit one whole share at the proposed stop distance.')

            risk_usd = risk_per_share * qty
            notional = entry * qty
            remaining_risk -= risk_usd
            remaining_exposure -= notional
            plan.update({
                'validated_quantity': qty,
                'safe_max_quantity': safe_max,
                'notional_usd': float(notional),
                'planned_open_risk_usd': float(risk_usd),
                'planned_open_risk_pct': float(risk_usd / capital * Decimal('100')),
                'quantity_was_clipped': bool(qty != astra_qty),
                'sizing_note': (
                    'Astra quantity accepted within limits.' if qty == astra_qty
                    else f'Astra proposed {astra_qty}; Python safety-capped to {qty}.'
                ),
            })
        except Exception as error:
            plan['validation_error'] = str(error)
            plan['valid'] = False
        plans.append(plan)
    return plans


def paper_quantity(plan, paper_max_order_usd):
    """Clip a validated strategy quantity to the explicit Alpaca PAPER notional cap."""
    if not plan.get('valid') or not plan.get('validated_quantity'):
        return None
    entry = _dec(plan['entry'])
    cap = _dec(paper_max_order_usd)
    max_by_paper = int((cap / entry).to_integral_value(rounding=ROUND_FLOOR))
    if max_by_paper < 1:
        return None
    return min(int(plan['validated_quantity']), max_by_paper)
