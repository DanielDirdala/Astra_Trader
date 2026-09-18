"""One local research cycle; no trade approval or submission.

A Windows Task Scheduler job may call this once per market morning. This script
does not install a job, keep a machine awake, or guarantee a model review succeeds.
"""
import argparse
import os
from src.us_market_ops import Settings,OpsStore,AlpacaHTTP,sync_history,capture_context,write_local


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true',help='Explicitly allow one billable Astra review after a successful capture')
    args=parser.parse_args()
    from src.universe import load_universe,get_universe
    from src.ops_review import review_context
    settings=Settings.load();store=OpsStore();api=AlpacaHTTP()
    try:
        failed=sync_history(api,store,get_universe(),settings)
        if failed:
            print('History refresh had errors. Paid review not started. Resolve errors or use an explicit partial capture.')
            return 1
        context=capture_context(api,store,settings,load_universe())
        write_local(context['context_id']+'.context.json',context)
        review_context(store,context,os.getenv('ASTRA_MODEL','gpt-6-astra'),args.send)
    finally:
        api.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
