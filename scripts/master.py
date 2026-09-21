"""One-command research pipeline: sync -> capture -> Python finalists -> optional Astra review.

This script NEVER submits a brokerage order. If Astra returns BUY research proposals,
it prints the exact follow-up command for preparing a paper ticket. The separate paper
submission command still requires the existing exact typed approval.
"""
from __future__ import annotations

import argparse
import os
from decimal import Decimal, InvalidOperation


def fnum(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def money(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        v = Decimal(str(value))
        return v if v.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def print_python_finalists(payload, audit):
    print('\nPYTHON FINALISTS')
    print('=================')
    print('Source shortlist:', payload.get('finalist_policy', {}).get('source_shortlist_size'))
    if not payload.get('candidates'):
        print('No eligible finalists. No model review should be sent from this capture.')
        return
    for i, c in enumerate(payload['candidates'], 1):
        q = c.get('quantitative') or {}
        live = c.get('live_market') or {}
        print(f"{i}. {c['symbol']} | {c.get('sector') or 'Unknown'}")
        print(f"   technical_score={q.get('technical_score')}  price={q.get('price')}  "
              f"5D={q.get('return_5d')}% 20D={q.get('return_20d')}%")
        print(f"   RSI={q.get('rsi_14')} ATR%={q.get('atr_pct')} volume_ratio={q.get('volume_ratio')}")
        print(f"   quote_fresh={live.get('quote_fresh')} spread_bps={live.get('spread_bps')} "
              f"quote_age={live.get('quote_age_seconds')}s")
        headlines = [n.get('headline') for n in c.get('recent_news', []) if n.get('headline')]
        if headlines:
            print('   news:', ' | '.join(headlines[:2]))
    excluded = audit.get('excluded') or {}
    if excluded:
        print(f"Eligible finalists chosen after excluding {len(excluded)} source candidates for data/account checks.")


def print_astra_report(row):
    report = row.get('final_report') or {}
    evaluations = report.get('evaluations') or []
    candidates = {c['symbol']: c for c in (row.get('input_payload') or {}).get('candidates', [])}

    print('\nASTRA FINAL REVIEW')
    print('==================')
    print('Review ID:', row['id'])
    summary = report.get('market_summary')
    if summary:
        print('Market summary:', summary)

    buy_count = 0
    for i, ev in enumerate(evaluations, 1):
        symbol = ev.get('symbol', '?')
        decision = ev.get('decision', '?')
        c = candidates.get(symbol, {})
        q = c.get('quantitative') or {}
        live = c.get('live_market') or {}
        print(f"\n{i}. {symbol} — {decision} | {c.get('sector') or 'Unknown'}")
        print('   Thesis:', ev.get('thesis') or 'N/A')
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
        print(f"   Current evidence: price={q.get('price')} technical_score={q.get('technical_score')} "
              f"quote_fresh={live.get('quote_fresh')} spread_bps={live.get('spread_bps')}")

        entry, stop, target = map(money, (ev.get('entry_price'), ev.get('stop_price'), ev.get('target_price')))
        if decision == 'BUY':
            buy_count += 1
            if entry is not None and stop is not None and target is not None and stop < entry < target:
                risk = entry - stop
                reward = target - entry
                rr = reward / risk if risk > 0 else None
                print(f"   Proposed order: BUY limit entry=${entry:.2f} | stop=${stop:.2f} | target=${target:.2f}")
                if rr is not None:
                    print(f"   Reward/risk: {rr:.2f}:1 | risk/share=${risk:.2f} | reward/share=${reward:.2f}")
                print('   Holding days:', ev.get('expected_holding_days'))
                print('   Prepare 1-share PAPER ticket:')
                print(f"   python -m scripts.trader paper prepare --review {row['id']} --symbol {symbol} --qty 1")
            else:
                print('   BUY research proposal has incomplete/invalid order prices; do not prepare a ticket.')

    if buy_count == 0:
        print('\nNO BUY SETUP THIS RUN.')
        print('No paper ticket should be prepared merely to force a trade.')
    else:
        print('\nNothing above was submitted to Alpaca. Prepare and inspect a paper ticket separately, then use the existing exact typed approval to submit it.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-sync', action='store_true', help='Use already-synced daily cache for this run.')
    parser.add_argument('--send-astra', action='store_true', help='Authorize one paid Astra review after capture.')
    parser.add_argument('--per-sector', type=int, default=3)
    parser.add_argument('--extra', type=int, default=5)
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    from src.us_market_ops import ROOT, Settings, OpsStore, AlpacaHTTP, sync_history, capture_context
    from src.universe import get_universe, load_universe
    from src.research_engine import CostPolicy, build_finalist_input, run_review

    load_dotenv(ROOT / '.env')
    settings = Settings.load()
    store = OpsStore()
    api = AlpacaHTTP()
    try:
        universe = load_universe()
        symbols = get_universe()
        print('ASTRA MASTER RESEARCH PIPELINE')
        print('==============================')
        print('Universe source:', universe.get('fund'), '| symbols:', len(symbols))

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
        payload, audit = build_finalist_input(context, policy)
        print_python_finalists(payload, audit)

        if not args.send_astra:
            print('\n[3/3] Astra not sent. Preview complete.')
            print('To request Astra on this fresh capture, rerun master promptly with --skip-sync --send-astra, or use:')
            print(f"python -m scripts.trader review --context {context['context_id']} --send")
            return 0

        print('\n[3/3] GPT-6 Astra finalist review')
        rc = run_review(store, context, model=os.getenv('ASTRA_MODEL') or 'gpt-6-astra', send=True, policy=policy)
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
        print_astra_report(row)
        return 0
    finally:
        api.close()


if __name__ == '__main__':
    raise SystemExit(main())
