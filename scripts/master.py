"""One-command research pipeline: sync -> capture -> quality gate -> Astra -> trade plans.

This script NEVER submits a brokerage order. Astra may propose up to three BUY plans.
Python independently validates/caps quantity. The separate PAPER submission command
still requires the existing exact typed approval.
"""
from __future__ import annotations

import argparse
import os
from decimal import Decimal, InvalidOperation


def money(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        v = Decimal(str(value))
        return v if v.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def print_sizing_policy(sizing):
    print('\nPOSITION-SIZING POLICY')
    print('======================')
    if sizing.strategy_capital_usd is None:
        print('Strategy capital: NOT SET')
        print('Set ASTRA_STRATEGY_CAPITAL_USD in .env or pass --capital to calculate whole-share plans.')
    else:
        print(f'Strategy capital: ${sizing.strategy_capital_usd:,.2f}')
    print(f'Risk tiers: low={sizing.low_risk_pct}% | medium={sizing.medium_risk_pct}% | high={sizing.high_risk_pct}%')
    print(f'Max position: {sizing.max_position_pct}% | max total exposure: {sizing.max_total_exposure_pct}% | '
          f'max total open risk: {sizing.max_total_risk_pct}%')
    print(f'Minimum reward/risk: {sizing.min_reward_risk}:1')


def print_python_finalists(payload, audit):
    print('\nPYTHON FINALISTS')
    print('=================')
    print('Source shortlist:', payload.get('finalist_policy', {}).get('source_shortlist_size'))
    print('Eligible after quality/event gate:', payload.get('finalist_policy', {}).get('eligible_source_candidates'))
    if not payload.get('candidates'):
        print('No eligible finalists. No model review should be sent from this capture.')
        excluded = audit.get('excluded') or {}
        if excluded:
            print('Excluded by data/event/setup checks:', len(excluded))
        return
    for i, c in enumerate(payload['candidates'], 1):
        q = c.get('quantitative') or {}
        live = c.get('live_market') or {}
        qp = c.get('quality_profile') or {}
        print(f"{i}. {c['symbol']} | {c.get('sector') or 'Unknown'}")
        print(f"   setup={qp.get('setup_type')} setup_score={qp.get('setup_score')} "
              f"rank_score={qp.get('finalist_rank_score')}")
        print(f"   technical_score={q.get('technical_score')} price={q.get('price')} "
              f"5D={q.get('return_5d')}% 20D={q.get('return_20d')}% RS/SPY={q.get('relative_strength_spy')}%")
        print(f"   RSI={q.get('rsi_14')} ATR%={q.get('atr_pct')} volume_ratio={q.get('volume_ratio')} "
              f"MACD_hist={q.get('macd_histogram')}")
        print(f"   quote_fresh={live.get('quote_fresh')} spread_bps={live.get('spread_bps')} "
              f"quote_age={live.get('quote_age_seconds')}s")
        soft = qp.get('soft_event_flags') or []
        if soft:
            print('   special-risk flags:', ', '.join(soft))
        headlines = [n.get('headline') for n in c.get('recent_news', []) if n.get('headline')]
        if headlines:
            print('   news:', ' | '.join(headlines[:2]))
    excluded = audit.get('excluded') or {}
    if excluded:
        print(f'Excluded {len(excluded)} source candidates for data/account/event/setup checks.')


def print_astra_report(row, settings):
    from src.trade_planner import SizingPolicy, build_trade_plans, paper_quantity

    report = row.get('final_report') or {}
    evaluations = report.get('evaluations') or []
    payload = row.get('input_payload') or {}
    candidates = {c['symbol']: c for c in payload.get('candidates', [])}
    sizing = SizingPolicy.from_payload(payload.get('sizing_policy'))
    plans = {p['symbol']: p for p in build_trade_plans(report, payload, sizing)}

    print('\nASTRA FINAL REVIEW')
    print('==================')
    print('Review ID:', row['id'])
    summary = report.get('market_summary')
    if summary:
        print('Market summary:', summary)

    buy_count = 0
    usable_count = 0
    for i, ev in enumerate(evaluations, 1):
        symbol = ev.get('symbol', '?')
        decision = ev.get('decision', '?')
        c = candidates.get(symbol, {})
        q = c.get('quantitative') or {}
        live = c.get('live_market') or {}
        qp = c.get('quality_profile') or {}
        print(f"\n{i}. {symbol} - {decision} | {c.get('sector') or 'Unknown'}")
        print('   Setup:', ev.get('setup_type') or qp.get('setup_type') or 'N/A')
        print('   Thesis:', ev.get('thesis') or 'N/A')
        if ev.get('entry_rationale'):
            print('   Entry rationale:', ev['entry_rationale'])
        if ev.get('bull_case'):
            print('   Bull case:', ev['bull_case'])
        if ev.get('bear_case'):
            print('   Bear case:', ev['bear_case'])
        invalidation = ev.get('invalidation') or ev.get('invalidation_reason')
        if invalidation:
            print('   Invalidation:', invalidation)
        risks = ev.get('risks') or []
        if risks:
            print('   Risks:', '; '.join(str(x) for x in risks[:3]))
        print(f"   Evidence: price={q.get('price')} technical_score={q.get('technical_score')} "
              f"setup_score={qp.get('setup_score')} quote_fresh={live.get('quote_fresh')} spread_bps={live.get('spread_bps')}")

        if decision != 'BUY':
            continue
        buy_count += 1
        plan = plans.get(symbol) or {}
        if not plan.get('valid'):
            print('   BUY plan FAILED Python validation:', plan.get('validation_error') or 'unknown validation error')
            print('   No paper ticket should be prepared from this plan.')
            continue

        entry = money(plan.get('entry'))
        stop = money(plan.get('stop'))
        target = money(plan.get('target'))
        print(f'   Proposed order: BUY limit ${entry:.2f} | stop ${stop:.2f} | target ${target:.2f}')
        print(f"   Reward/risk: {plan.get('reward_risk'):.2f}:1 | stop distance: ${plan.get('risk_per_share'):.2f}/share")
        if plan.get('stop_atr_multiple') is not None:
            print(f"   Stop distance: {plan.get('stop_atr_multiple'):.2f} ATR")
        print('   Risk tier:', ev.get('risk_tier'))
        print('   Expected holding days:', ev.get('expected_holding_days'), '| time stop:', ev.get('time_stop_days'))
        if ev.get('exit_rule'):
            print('   Indicator exit rule:', ev['exit_rule'])

        astra_qty = plan.get('astra_suggested_quantity')
        validated_qty = plan.get('validated_quantity')
        if sizing.strategy_capital_usd is None:
            print('   Astra shares: not calculated because strategy capital is not configured.')
            print('   Set --capital or ASTRA_STRATEGY_CAPITAL_USD before using this as a sized trade plan.')
            continue
        print(f'   Astra proposed shares: {astra_qty}')
        print(f'   Python-validated strategy shares: {validated_qty}')
        print(f"   Planned notional: ${plan.get('notional_usd'):,.2f} | "
              f"open risk: ${plan.get('planned_open_risk_usd'):,.2f} ({plan.get('planned_open_risk_pct'):.3f}% of strategy capital)")
        if plan.get('quantity_was_clipped'):
            print('   Sizing guard:', plan.get('sizing_note'))

        pqty = paper_quantity(plan, settings.max_order_usd)
        if pqty is None:
            print(f'   PAPER quantity unavailable under the current ${settings.max_order_usd:,.2f} paper-order cap.')
            continue
        usable_count += 1
        paper_notional = float(entry) * pqty
        if pqty != validated_qty:
            print(f'   Alpaca PAPER quantity: {pqty} shares (clipped by ${settings.max_order_usd:,.2f} paper-test cap; ~${paper_notional:,.2f})')
        else:
            print(f'   Alpaca PAPER quantity: {pqty} shares (~${paper_notional:,.2f})')
        print('   Prepare this PAPER ticket:')
        print(f"   python -m scripts.trader paper prepare --review {row['id']} --symbol {symbol} --qty {pqty}")

    if buy_count == 0:
        print('\nNO BUY SETUP THIS RUN.')
        print('No paper ticket should be prepared merely to force a trade.')
    elif usable_count == 0:
        print('\nAstra returned BUY research, but none produced a validated/sized paper ticket.')
    else:
        print(f'\nValidated paper-ticket candidates: {usable_count}. Nothing was submitted to Alpaca.')
        print('Prepare only the order(s) you want to inspect. Each actual paper submission still requires the exact typed approval.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-sync', action='store_true', help='Use already-synced daily cache for this run.')
    parser.add_argument('--send-astra', action='store_true', help='Authorize one paid Astra review after capture.')
    parser.add_argument('--per-sector', type=int, default=3)
    parser.add_argument('--extra', type=int, default=5)
    parser.add_argument('--capital', type=Decimal, help='Capital allocated to this strategy; overrides ASTRA_STRATEGY_CAPITAL_USD for this run.')
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    from src.us_market_ops import ROOT, Settings, OpsStore, AlpacaHTTP, sync_history, capture_context
    from src.universe import get_universe, load_universe
    from src.research_engine import CostPolicy, build_finalist_input, run_review
    from src.trade_planner import SizingPolicy

    load_dotenv(ROOT / '.env')
    settings = Settings.load()
    sizing = SizingPolicy.load(capital_override=args.capital)
    store = OpsStore()
    api = AlpacaHTTP()
    try:
        universe = load_universe()
        symbols = get_universe()
        print('ASTRA MASTER RESEARCH PIPELINE')
        print('==============================')
        print('Universe source:', universe.get('fund'), '| symbols:', len(symbols))
        print_sizing_policy(sizing)

        if not args.skip_sync:
            print('\n[1/3] Incremental daily-data sync')
            failed = sync_history(api, store, symbols, settings, force_full=False)
            if failed:
                raise RuntimeError(f'History sync reported {failed} failed symbols; resolve before a paid review.')
        else:
            print('\n[1/3] Sync skipped by user.')

        print('\n[2/3] Fresh market/news/account capture')
        context = capture_context(api, store, settings, universe, per_sector=args.per_sector, extra=args.extra)
        print('Context ID:', context['context_id'])
        print('Daily target:', context['daily_target_session'])
        print('Screened:', context['screened_count'], '| candidates:', len(context['candidates']),
              '| excluded:', len(context['excluded']), '| market open:', context['market_clock']['is_open'])

        policy = CostPolicy.load()
        payload, audit = build_finalist_input(context, policy, sizing_policy=sizing)
        print_python_finalists(payload, audit)

        if not args.send_astra:
            print('\n[3/3] Astra not sent. Preview complete.')
            if sizing.strategy_capital_usd is None:
                print('Add --capital YOUR_STRATEGY_CAPITAL to the paid master run if you want Astra to propose whole-share size.')
            print('To request Astra on a fresh capture, rerun master promptly with --skip-sync --send-astra.')
            return 0

        print('\n[3/3] GPT-6 Astra finalist review')
        rc = run_review(store, context, model=os.getenv('ASTRA_MODEL') or 'gpt-6-astra', send=True,
                        policy=policy, sizing_policy=sizing)
        if rc != 0:
            return rc

        from src.ops_review import make_review_store
        reviews = make_review_store()
        row, usage = reviews.get_review()
        if not row or str((row.get('input_payload') or {}).get('context_id')) != str(context['context_id']):
            print('Astra request was created/handled, but the matching latest review could not be identified safely.')
            print('Use: python -m scripts.trader report')
            return 1
        if row['status'] != 'COMPLETED':
            print('Review status:', row['status'])
            if row.get('response_id'):
                print(f"Resume without another generation: python -m scripts.trader resume --review {row['id']}")
            return 0
        if usage and usage.get('cost_high_usd') is not None:
            print(f"Recorded model cost estimate: ${usage['cost_low_usd']:.4f}-${usage['cost_high_usd']:.4f}")
        print_astra_report(row, settings)
        return 0
    finally:
        api.close()


if __name__ == '__main__':
    raise SystemExit(main())
