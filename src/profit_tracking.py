"""Reporting and planning only. Never used by the selector or the order executor."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.pnl_tracker import PnLTracker, decimal_number, money
from src.us_market_ops import utcnow


def goal_plan(capital: Any = None, *, days: int = 14, low: Any = 100,
              high: Any = 200, costs: Any = None) -> dict:
    """Return arithmetic for a calendar-day reporting goal, not a forecast."""
    if type(days) is not int or days not in (7, 14):
        raise ValueError('Choose 7 or 14 calendar days.')
    low, high = decimal_number(low), decimal_number(high)
    if not Decimal(0) <= low <= high:
        raise ValueError('Targets must satisfy 0 <= low <= high.')
    capital = decimal_number(capital) if capital is not None else None
    costs = decimal_number(costs) if costs is not None else None
    if capital is not None and capital <= 0:
        raise ValueError('Allocated, unlevered capital must be positive.')
    if costs is not None and costs < 0:
        raise ValueError('Period external operating costs cannot be negative.')
    gross = [low+costs, high+costs] if costs is not None else None
    required = [money(v/capital*100) for v in gross] if capital is not None and gross else None
    return {
        'period_calendar_days': days,
        'target_net_before_tax_usd': [money(low), money(high)],
        'allocated_capital_usd': money(capital) if capital is not None else None,
        'external_costs_usd': money(costs) if costs is not None else None,
        'required_after_broker_fees_before_external_costs_usd': [money(v) for v in gross] if gross else None,
        'required_return_on_allocated_capital_pct': required,
        'meaning': 'Arithmetic only; not a probability, forecast, sizing rule, or requirement to trade.',
        'missing': [name for name, v in [('allocated_capital', capital), ('external_costs', costs)] if v is None],
    }


def paper_profit_report(api, *, days=14, capital=None, external_costs=None,
                        low=100, high=200) -> dict:
    """Read paper-account fills; unknown basis/events fail closed. No DB writes."""
    plan = goal_plan(capital, days=days, low=low, high=high, costs=external_costs)
    account = api.get('/v2/account', trading=True)
    if not account.get('created_at') or not account.get('id') or account.get('currency') != 'USD':
        raise ValueError('USD paper account creation time and identity are required.')
    as_of = utcnow()
    activities = PnLTracker(api).fetch_activities(account['created_at'], as_of)
    positions = api.get('/v2/positions', trading=True)
    check_account = api.get('/v2/account', trading=True)
    if check_account.get('id') != account['id']:
        raise ValueError('Account changed while collecting the report.')
    result = PnLTracker.calculate(
        activities, positions, account_created_at=account['created_at'], as_of=as_of,
        period_days=days, history_complete=True, external_costs_usd=external_costs,
    )
    result['goal'] = plan
    result['scope'] = 'All returned paper-account activity, including manual and other-program trades; not bot-only.'
    result['paper_only'] = True
    result['goal_status'] = 'unavailable'
    net = result['net_realized_after_known_costs_usd']
    if net is not None:
        net = decimal_number(net)
        result['goal_status'] = 'below' if net < decimal_number(low) else 'above' if net > decimal_number(high) else 'within'
    result['limitations'].extend([
        'No change to model instructions, position sizes, or order limits follows from this report.',
        'Provider retrieval cannot prove that no historical records were omitted; inspect the broker statement.',
        'Fees can post later. This is an as-observed research ledger, not a tax or final accounting statement.',
        'API/data/other costs must be supplied for this reporting window; missing costs are not zero.',
    ])
    return result
