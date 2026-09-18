"""Explicit approval workflow for PAPER long limit-bracket orders only."""
import argparse
import time
from uuid import UUID

from src.us_market_ops import Settings,AlpacaHTTP,canonical
from src.paper_tickets import TicketStore


def show(remote,ticket=None):
    if remote is None:
        print('Order not found by client ID. This is NOT proof that a timed-out submission never reached Alpaca.')
        if ticket:
            print('Ticket state:',ticket['state'],'; client order ID:',ticket['client_order_id'])
        return
    print('Broker order ID:',remote.get('id'))
    print('Status:',remote.get('status'),'filled:',remote.get('filled_qty'),'of',remote.get('qty'))
    if remote.get('status')=='partially_filled':
        print('WARNING: bracket exits activate after the parent is FULLY filled; inspect partial exposure in Alpaca.')
    for child in remote.get('legs') or []:
        print('  Exit leg:',child.get('type'),child.get('status'),child.get('filled_qty'))
    print('Submitted/accepted is not the same as filled. This command does not cancel or liquidate anything.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--review',type=UUID,required=True)
    prepare.add_argument('--symbol',required=True)
    prepare.add_argument('--qty',type=int,required=True)
    submit=sub.add_parser('submit')
    submit.add_argument('ticket',type=UUID)
    submit.add_argument('--ack-earnings-unknown',action='store_true')
    status=sub.add_parser('status')
    status.add_argument('ticket',type=UUID)
    watch=sub.add_parser('watch')
    watch.add_argument('ticket',type=UUID)
    watch.add_argument('--seconds',type=int,default=30)
    args=parser.parse_args()
    settings=Settings.load(); api=AlpacaHTTP(); store=TicketStore()
    try:
        if args.command=='prepare':
            ticket,checks=store.prepare(api,settings,args.review,args.symbol.strip().upper(),args.qty)
            print('Prepared ticket:',ticket['id'])
            print('Submit before:',ticket['submit_before'])
            print(canonical(ticket['order_payload']))
            print('Preflight:',checks)
            print('No order sent. Submission requires the separate submit command and exact typed approval.')
        elif args.command=='submit':
            show(store.submit(api,settings,args.ticket,ack_earnings_unknown=args.ack_earnings_unknown))
        else:
            if args.command=='watch' and args.seconds<15:
                raise ValueError('This paper monitor supports intervals of at least 15 seconds.')
            while True:
                ticket,remote=store.reconcile(api,args.ticket)
                show(remote,ticket)
                if args.command=='status':
                    break
                time.sleep(args.seconds)
    except KeyboardInterrupt:
        print('Local monitor stopped. Broker orders and positions remain open unless canceled/closed at Alpaca.')
    finally:
        api.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
