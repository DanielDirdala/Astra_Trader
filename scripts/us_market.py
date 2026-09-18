"""US market data operations. No brokerage orders; model calls only with review --send."""
import argparse
import os
from datetime import timedelta
from uuid import UUID

from src.us_market_ops import (Settings,OpsStore,AlpacaHTTP,ROOT,NY,utcnow,
                               sync_history,capture_context,write_local)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    adopt=sub.add_parser('adopt-legacy',help='Copy declared old IEX/raw daily bars; never deletes original history')
    adopt.add_argument('--symbols')
    adopt.add_argument('--confirm-iex-raw-provenance',action='store_true')
    sync=sub.add_parser('sync',help='Batch backfill/incremental update with periodic full reconciliation')
    sync.add_argument('--symbols')
    sync.add_argument('--full',action='store_true')
    capture=sub.add_parser('capture',help='Fresh sector shortlist, news, portfolio, and intraday snapshots')
    capture.add_argument('--per-sector',type=int,default=3)
    capture.add_argument('--extra',type=int,default=5)
    review=sub.add_parser('review',help='Preview by default; --send makes ONE billable model request')
    review.add_argument('--context',type=UUID)
    review.add_argument('--send',action='store_true')
    args=parser.parse_args()
    settings=Settings.load(); store=OpsStore()
    if args.command=='init':
        store.initialize()
        print('Four additive operational tables checked. Existing data and old scripts were not changed.')
        return 0
    if args.command=='review':
        from src.ops_review import review_context
        context=store.context(args.context)
        return review_context(store,context,os.getenv('ASTRA_MODEL','gpt-6-astra') or 'gpt-6-astra',args.send)
    from src.universe import get_universe,load_universe
    if args.command in ('sync','adopt-legacy'):
        symbols=sorted({s.strip().upper() for s in args.symbols.split(',') if s.strip()}) if args.symbols else get_universe()
        if not symbols:
            raise ValueError('No symbols requested.')
    if args.command=='adopt-legacy':
        if not args.confirm_iex_raw_provenance:
            print('No changes made. This is ONLY for old bars you know came from IEX with adjustment=raw.')
            print('Use --confirm-iex-raw-provenance to attest to that origin. Unknown/mixed feeds should be fetched afresh.')
            return 0
        cutoff=utcnow().astimezone(NY).date()-timedelta(days=1)
        count=store.adopt_legacy(symbols,settings,cutoff)
        print(f'{count} legacy rows examined for copying; conflicts preserved. Original tables unchanged.')
        return 0
    api=AlpacaHTTP()
    try:
        if args.command=='sync':
            return 1 if sync_history(api,store,symbols,settings,force_full=args.full) else 0
        if not 1<=args.per_sector<=10 or not 0<=args.extra<=20:
            raise ValueError('Use per-sector 1-10 and extra 0-20.')
        context=capture_context(api,store,settings,load_universe(),per_sector=args.per_sector,extra=args.extra)
        print(f"Context ID: {context['context_id']}; daily target: {context['daily_target_session']}")
        print(f"Universe: {context['universe_count']}; current history screened: {context['screened_count']}; excluded: {len(context['excluded'])}")
        print(f"Candidates: {len(context['candidates'])}; regular market open: {context['market_clock']['is_open']}")
        for c in context['candidates']:
            live=c['live_market']
            print(f"{c['symbol']:<8} {c['sector']:<25} quote age={live['quote_age_seconds']}s; quote fresh={live['quote_fresh']}; news={c['news_fetch_status']}")
        print('Saved context:',write_local(context['context_id']+'.context.json',context))
        print('No OpenAI requests or brokerage orders made.')
        return 0
    finally:
        api.close()


if __name__=='__main__':
    raise SystemExit(main())
