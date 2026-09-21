"""One supported entry point for the consolidated Astra Trader workflow."""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID


@contextmanager
def argv_for(module, args):
    previous = sys.argv
    sys.argv = [module] + args
    try:
        yield
    finally:
        sys.argv = previous


def delegate(module, args):
    import importlib
    with argv_for(module, args):
        return importlib.import_module(module).main() or 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor', help='Local checks; --db explicitly checks PostgreSQL read-only')
    doctor.add_argument('--db', action='store_true')
    sub.add_parser('test', help='Offline test suite: no network/account writes')
    sub.add_parser('init', help='Additive DDL and schema verification; back up the DB first')
    adopt = sub.add_parser('adopt-legacy', help='Reuse known IEX/raw history; preview without confirmation')
    adopt.add_argument('--symbols')
    adopt.add_argument('--confirm-iex-raw-provenance', action='store_true')
    sync = sub.add_parser('sync', help='Incremental history update')
    sync.add_argument('--symbols')
    sync.add_argument('--full', action='store_true')
    capture = sub.add_parser('capture', help='Python screen, news and current snapshots; no Astra call')
    capture.add_argument('--per-sector', type=int, default=3)
    capture.add_argument('--extra', type=int, default=5)
    review = sub.add_parser('review', help='Three-finalist preview; --send creates one resumable background response')
    review.add_argument('--context', type=UUID, required=True)
    review.add_argument('--send', action='store_true')
    resume = sub.add_parser('resume', help='Poll an existing background Astra response; never creates a generation')
    resume.add_argument('--review', type=UUID, required=True)
    resume.add_argument('--wait-seconds', type=int, default=120)
    cancel = sub.add_parser('cancel-review', help='Cancel an existing background Astra response')
    cancel.add_argument('--review', type=UUID, required=True)
    reconcile = sub.add_parser('reconcile', help='Manually record cost for an old uncertain review; no API call')
    reconcile.add_argument('--review', type=UUID, required=True)
    reconcile.add_argument('--cost-low', type=Decimal, required=True)
    reconcile.add_argument('--cost-high', type=Decimal, required=True)
    reconcile.add_argument('--reason', required=True)
    sub.add_parser('usage', help='Read recorded model usage; no network or generation')
    report = sub.add_parser('report', help='Read a saved model review')
    report.add_argument('--review', type=UUID)
    for name in ('goal', 'pnl'):
        part = sub.add_parser(name, help='Offline planning' if name == 'goal' else 'Read-only paper-account P&L estimate')
        part.add_argument('--days', type=int, choices=(7,14), default=14)
        part.add_argument('--capital', type=Decimal)
        part.add_argument('--costs', type=Decimal, help='Verified external costs for this entire window; omitted = UNKNOWN')
        part.add_argument('--target-low', type=Decimal, default=Decimal('100'))
        part.add_argument('--target-high', type=Decimal, default=Decimal('200'))
    master = sub.add_parser('master', help='Run sync -> capture -> finalists -> optional Astra review; never submits an order')
    master.add_argument('--skip-sync', action='store_true')
    master.add_argument('--send-astra', action='store_true')
    master.add_argument('--per-sector', type=int, default=3)
    master.add_argument('--extra', type=int, default=5)
    paper = sub.add_parser('paper', help='Separate exact-order human approval workflow; paper only')
    paper.add_argument('paper_args', nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == 'test':
        return delegate('scripts.test_all', [])
    from src.us_market_ops import ROOT
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    if args.command in ('doctor', 'init'):
        from src.project_health import doctor, initialize
        return doctor(args.db) if args.command == 'doctor' else initialize()
    if args.command in ('sync','adopt-legacy','capture'):
        forwarded = [args.command]
        if args.command in ('sync','adopt-legacy') and args.symbols:
            forwarded += ['--symbols', args.symbols]
        if args.command == 'sync' and args.full:
            forwarded += ['--full']
        if args.command == 'adopt-legacy' and args.confirm_iex_raw_provenance:
            forwarded += ['--confirm-iex-raw-provenance']
        if args.command == 'capture':
            forwarded += ['--per-sector', str(args.per_sector), '--extra', str(args.extra)]
        return delegate('scripts.us_market', forwarded)
    if args.command == 'review':
        from src.us_market_ops import OpsStore
        from src.research_engine import run_review
        store = OpsStore()
        return run_review(store,store.context(args.context),model=os.getenv('ASTRA_MODEL') or 'gpt-6-astra',send=args.send)
    if args.command == 'resume':
        from src.research_engine import resume_review
        return resume_review(args.review, wait_seconds=args.wait_seconds)
    if args.command == 'cancel-review':
        from src.research_engine import cancel_review
        return cancel_review(args.review)
    if args.command == 'reconcile':
        from src.research_engine import reconcile_review
        return reconcile_review(args.review, args.cost_low, args.cost_high, args.reason)
    if args.command == 'usage':
        from src.research_engine import budget_snapshot, usage_rows
        from src.ops_review import make_review_store
        rows = usage_rows(make_review_store())
        for row in rows:
            print(row['id'], row['started_at'], row['status'], 'policy=',row.get('prompt_version'),
                  'response=',row.get('response_id'), 'tier=',row.get('service_tier'),
                  'input=',row.get('input_tokens'), 'output=',row.get('output_tokens'),
                  'reasoning subset=',row.get('reasoning_tokens'), 'estimated USD=',row.get('cost_high_usd'))
        state = budget_snapshot(rows)
        print('All recorded/reconciled upper token-cost estimate:', state['committed_usd'])
        print('Unknown-cost IDs:', state['unknown_ids'])
        print('Reporting is broader than the v0.3 rolling budget. Not an account-wide invoice.')
        return 0
    if args.command == 'report':
        # Reuse the stored-report reader but accept the CLI's supported --review spelling.
        return delegate('scripts.view_astra_review', ['--id', str(args.review)] if args.review else [])
    if args.command in ('goal','pnl'):
        import json
        from src.profit_tracking import goal_plan, paper_profit_report
        if args.command == 'goal':
            result = goal_plan(args.capital,days=args.days,low=args.target_low,high=args.target_high,costs=args.costs)
        else:
            from src.us_market_ops import AlpacaHTTP
            api = AlpacaHTTP()
            try:
                result = paper_profit_report(api,days=args.days,capital=args.capital,external_costs=args.costs,
                                             low=args.target_low,high=args.target_high)
            finally:
                api.close()
        print(json.dumps(result, indent=2))
        return 0 if args.command == 'goal' or result['complete'] else 1
    if args.command == 'master':
        forwarded = []
        if args.skip_sync:
            forwarded.append('--skip-sync')
        if args.send_astra:
            forwarded.append('--send-astra')
        forwarded += ['--per-sector', str(args.per_sector), '--extra', str(args.extra)]
        return delegate('scripts.master', forwarded)
    if args.command == 'paper':
        return delegate('scripts.paper_order', args.paper_args)
    raise AssertionError('Unrecognized command')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Stopped locally. Broker orders, if any, were NOT canceled.')
        raise SystemExit(130)
