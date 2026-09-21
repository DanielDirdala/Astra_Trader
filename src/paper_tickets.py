"""Explicit human-approved, whole-share LONG bracket entries. PAPER endpoint only.

Not a general broker adapter: no live switch, shorting, auto-approval, or resizing.
A request timeout is UNKNOWN. It is NEVER automatically submitted again.
"""
from __future__ import annotations
import os

import hashlib
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from src.us_market_ops import (AlpacaHTTP, OpsStore, PAPER_URL, ROOT, NY,
                               canonical, stamp, utcnow, quote_context, number)

GLOBAL_ORDER_LOCK = 76321482


def money(value):
    if isinstance(value, bool):
        raise ValueError('Invalid price.')
    try:
        result=Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid price.') from None
    if not result.is_finite() or result < 1 or result > Decimal('1000000'):
        raise ValueError('This prototype supports finite prices from $1 through $1,000,000.')
    if result != result.quantize(Decimal('0.01')):
        raise ValueError('Price has more than two decimals. Do not silently round an approved order.')
    return result


def create_order(symbol, quantity, entry, stop, target, client_id):
    if not isinstance(quantity,int) or isinstance(quantity,bool) or not 1<=quantity<=10000:
        raise ValueError('Whole positive share quantities only, maximum 10,000.')
    if not isinstance(symbol,str) or not symbol or symbol!=symbol.upper() or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}',symbol):
        raise ValueError('Invalid stock symbol.')
    entry,stop,target=map(money,(entry,stop,target))
    if not stop<entry<target:
        raise ValueError('Long bracket must have stop < entry < target.')
    return {'symbol':symbol,'qty':str(quantity),'side':'buy','type':'limit',
            'time_in_force':'gtc','limit_price':str(entry),'order_class':'bracket',
            'take_profit':{'limit_price':str(target)},'stop_loss':{'stop_price':str(stop)},
            'extended_hours':False,'client_order_id':client_id}


def order_hash(order):
    return hashlib.sha256(canonical(order).encode()).hexdigest()


def preflight(order, account, positions, orders, asset, clock, calendar_today, live, settings, *, now=None):
    """Checks before approval AND again immediately before submission; no predictions."""
    now=now or utcnow()
    if (ROOT/'STOP_TRADING').exists():
        raise ValueError('STOP_TRADING exists. No new entry will be submitted.')
    if account.get('status')!='ACTIVE' or account.get('currency')!='USD':
        raise ValueError('An active USD paper account is required.')
    if any(account.get(k) is not False for k in ('trading_blocked','account_blocked','trade_suspended_by_user')):
        raise ValueError('Account is blocked or trading permissions could not be verified.')
    if abs((now-stamp(clock['timestamp'])).total_seconds())>30:
        raise ValueError('Broker clock is stale or system clock differs.')
    if not clock.get('is_open') or len(calendar_today)!=1:
        raise ValueError('New entries are only submitted during a verified regular US market session.')
    session=calendar_today[0]
    local=now.astimezone(NY)
    if session['date']!=local.date().isoformat():
        raise ValueError('Calendar date mismatch.')
    from datetime import datetime, time, date
    start=datetime.combine(date.fromisoformat(session['date']),time.fromisoformat(session['open']),NY).astimezone(now.tzinfo)
    end=datetime.combine(date.fromisoformat(session['date']),time.fromisoformat(session['close']),NY).astimezone(now.tzinfo)
    if not start<=now<end:
        raise ValueError('Not inside the regular-hours calendar window (including early close).')
    if asset.get('class')!='us_equity' or asset.get('status')!='active' or asset.get('tradable') is not True:
        raise ValueError('Symbol is not confirmed active/tradable US equity.')
    if any(p.get('symbol')==order['symbol'] for p in positions):
        raise ValueError('An existing position in this symbol requires separate management, not another entry.')
    if any(o.get('symbol')==order['symbol'] for o in orders):
        raise ValueError('An existing order in this symbol must be resolved first.')
    if not live.get('executable_quote_check') or live['spread_bps'] is None or live['spread_bps']>50:
        raise ValueError('Missing/stale/crossed quote or spread exceeds the prototype 50 bps guard.')
    if abs(live['midpoint']/float(order['limit_price'])-1)>0.03:
        raise ValueError('Proposed entry is over 3% from fresh midpoint; obtain a new review rather than reprice silently.')
    notional=Decimal(order['qty'])*money(order['limit_price'])
    if notional>Decimal(str(settings.max_order_usd)):
        raise ValueError(f'Order exceeds the explicit ${settings.max_order_usd:,.2f} paper-test notional cap.')
    reserved=Decimal(0)
    for o in orders:
        if o.get('side')!='buy':
            continue
        qty=number(o.get('qty')); filled=number(o.get('filled_qty'))
        price=number(o.get('limit_price')) or number(o.get('stop_price'))
        if qty is None or filled is None or price is None or price<=0:
            raise ValueError('Cannot conservatively value another open buy order; resolve it before this prototype entry.')
        reserved+=Decimal(str(max(0,qty-filled)))*Decimal(str(price))
    cash=number(account.get('cash'))
    if cash is None or Decimal(str(cash))-reserved<notional:
        raise ValueError('Insufficient cash after reserving other open buys. This prototype does not use margin.')
    return {'notional_usd':str(notional),'cash_reserved_for_other_orders':str(reserved),
            'quote_age_seconds':live['quote_age_seconds'],'spread_bps':live['spread_bps']}


def get_checks(api,order,settings):
    account,positions,orders=api.account_context()
    asset=api.get('/v2/assets/'+order['symbol'],trading=True)
    snapshots=api.get('/v2/stocks/snapshots',{'symbols':order['symbol'],'feed':settings.feed})
    clock=api.get('/v2/clock',trading=True)
    now=utcnow(); today=now.astimezone(NY).date()
    calendar=api.calendar(today,today)
    live=quote_context(snapshots.get(order['symbol'],{}),now,settings.quote_max_age,clock['is_open'])
    checks=preflight(order,account,positions,orders,asset,clock,calendar,live,settings,now=now)
    return account,checks


class TicketStore(OpsStore):
    def ticket(self,identifier):
        with self.connect() as conn:
            row=conn.execute('SELECT * FROM public.astra_paper_tickets WHERE id=%s',(identifier,)).fetchone()
        if not row:
            raise ValueError('Paper ticket not found.')
        return row

    def prepare(self,api,settings,review_id,symbol,qty):
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            run=conn.execute('SELECT * FROM public.astra_review_runs WHERE id=%s',(review_id,)).fetchone()
        if not run or run['status']!='COMPLETED':
            raise ValueError('A completed Astra review is required.')
        payload=run['input_payload']
        if payload.get('ops_version')!='us-market-ops-v1':
            raise ValueError('Legacy historical-only review cannot become a ticket. Use the current-context review command.')
        if not -5 <= (utcnow()-stamp(payload['context_captured_at'])).total_seconds() <= 900:
            raise ValueError('Context is over 15 minutes old. Refresh capture and review before preparing a new entry.')
        evaluations=run['final_report']['evaluations']
        matches=[e for e in evaluations if e['symbol']==symbol and e['decision']=='BUY']
        if len(matches)!=1:
            raise ValueError('This symbol is not a unique BUY proposal in the selected review.')
        item=matches[0]
        from src.trade_planner import SizingPolicy, build_trade_plans, paper_quantity
        sizing = SizingPolicy.from_payload(payload.get('sizing_policy'))
        plans = {p['symbol']: p for p in build_trade_plans(run['final_report'], payload, sizing)}
        plan = plans.get(symbol)
        if not plan or not plan.get('valid') or not plan.get('validated_quantity'):
            raise ValueError('This BUY does not have a valid Python-sized trade plan. Re-run master with configured strategy capital.')
        paper_max = paper_quantity(plan, settings.max_order_usd)
        if paper_max is None:
            raise ValueError('Current paper-order notional cap does not permit one share of this validated plan.')
        if qty > paper_max:
            raise ValueError(f'Requested quantity {qty} exceeds the validated PAPER maximum {paper_max} shares.')
        item=matches[0]; identifier=uuid4(); client_id='astra-'+identifier.hex
        order=create_order(symbol,qty,item['entry_price'],item['stop_price'],item['target_price'],client_id)
        account,checks=get_checks(api,order,settings)
        checks['validated_strategy_quantity']=plan['validated_quantity']
        checks['validated_paper_max_quantity']=paper_max
        checks['risk_tier']=plan.get('risk_tier')
        checks['planned_open_risk_usd_for_requested_qty']=str(Decimal(str(plan['risk_per_share']))*qty)
        if not account.get('id'):
            raise ValueError('Paper account identity is missing.')
        expires=utcnow()+timedelta(minutes=5)
        with self.connect() as conn:
            row=conn.execute('''INSERT INTO public.astra_paper_tickets
                (id,review_id,symbol,account_id,client_order_id,state,order_payload,order_sha256,submit_before)
                VALUES (%s,%s,%s,%s,%s,'PREPARED',%s,%s,%s)
                ON CONFLICT(review_id,symbol) DO NOTHING RETURNING *''',
                (identifier,review_id,symbol,account['id'],client_id,Jsonb(order),order_hash(order),expires)).fetchone()
        if not row:
            raise ValueError('This review/symbol already has a ticket. Inspect it; do not create a duplicate entry.')
        return row,checks

    def reconcile(self,api,identifier):
        from psycopg.types.json import Jsonb
        ticket=self.ticket(identifier)
        account=api.get('/v2/account',trading=True)
        if account.get('id')!=ticket['account_id']:
            raise ValueError('Paper account differs from the ticket account.')
        remote=api.get('/v2/orders:by_client_order_id',{'client_order_id':ticket['client_order_id']},trading=True,allow_404=True)
        if remote is None:
            return ticket,None
        if remote.get('id'):
            remote=api.get('/v2/orders/'+remote['id'],{'nested':'true'},trading=True)
        if remote.get('symbol')!=ticket['symbol'] or remote.get('side')!='buy' or str(remote.get('client_order_id'))!=ticket['client_order_id']:
            raise ValueError('Broker order identity mismatch; investigate manually.')
        with self.connect() as conn:
            conn.execute('''UPDATE public.astra_paper_tickets SET state='SUBMITTED',
                broker_order=%s,last_checked_at=now(),error=NULL WHERE id=%s''',(Jsonb(remote),identifier))
        return ticket,remote

    def submit(self,api,settings,identifier,*,ask=input,ack_earnings_unknown=False):
        from psycopg.types.json import Jsonb
        if os.getenv('ASTRA_ENABLE_PAPER_SUBMISSION', 'false').lower() != 'true':
            raise RuntimeError('Paper submission is disabled. Enable ASTRA_ENABLE_PAPER_SUBMISSION=true only after verifying setup.')
        ticket=self.ticket(identifier)
        if ticket['state']!='PREPARED':
            return self.reconcile(api,identifier)[1]  # NEVER resend unknown/submitted attempts
        displayed_hash=order_hash(ticket['order_payload'])
        displayed_account=ticket['account_id']
        print('Exact approved-order contents:')
        print(canonical(ticket['order_payload']))
        print('PAPER ONLY. GTC entry may remain open across sessions; broker exits activate after full entry fill.')
        print('Approval expiry is for SUBMISSION, not cancellation of an accepted GTC order.')
        print('Earnings calendar is not connected. Stops do not guarantee a maximum loss.')
        if not ack_earnings_unknown:
            raise ValueError('Review event/earnings risk; --ack-earnings-unknown is required for this PAPER prototype.')
        expected='APPROVE PAPER '+str(identifier)
        if ask('Type '+expected+' to authorize this exact order: ').strip()!=expected:
            raise ValueError('Not approved; nothing submitted.')
        with self.connect() as conn:
            if not conn.execute('SELECT pg_try_advisory_lock(%s) AS locked',(GLOBAL_ORDER_LOCK,)).fetchone()['locked']:
                raise ValueError('Another order worker is active. Do not run two trading workers.')
            try:
                row=conn.execute('SELECT * FROM public.astra_paper_tickets WHERE id=%s FOR UPDATE',(identifier,)).fetchone()
                if row['state']!='PREPARED' or row['submit_before']<=utcnow():
                    raise ValueError('Ticket expired or was already used. No order sent.')
                if (order_hash(row['order_payload'])!=row['order_sha256']
                    or row['order_sha256']!=displayed_hash
                    or row['account_id']!=displayed_account):
                    raise ValueError('Order or account changed after preparation/display; approval is invalid.')
                unresolved=conn.execute("SELECT id FROM public.astra_paper_tickets WHERE state IN ('UNKNOWN','SUBMITTING') LIMIT 1").fetchone()
                if unresolved:
                    raise ValueError('Resolve the previous ambiguous submission in Alpaca before any new entry.')
                account,checks=get_checks(api,row['order_payload'],settings)
                if row['submit_before'] <= utcnow():
                    raise ValueError('Ticket expired during account/quote checks; no order submitted.')
                if account.get('id')!=row['account_id']:
                    raise ValueError('Account changed after ticket preparation.')
                conn.execute("""UPDATE public.astra_paper_tickets SET state='SUBMITTING',approved_at=now(),
                    acknowledged_earnings_unknown=TRUE WHERE id=%s""",(identifier,))
                conn.commit()  # Durable intent BEFORE the one network side effect.
                try:
                    # POST is intentionally not routed through the GET retry client.
                    response=api.session.post(PAPER_URL+'/v2/orders',json=row['order_payload'],
                                              timeout=(10,30),allow_redirects=False)
                    if response.status_code not in (200,201):
                        raise RuntimeError(f'Order POST returned HTTP {response.status_code}; reconcile before any further action.')
                    remote=response.json()
                    if remote.get('client_order_id')!=row['client_order_id'] or remote.get('symbol')!=row['symbol']:
                        raise RuntimeError('Unexpected broker response identity; reconcile.')
                except Exception as error:
                    conn.execute("UPDATE public.astra_paper_tickets SET state='UNKNOWN',error=%s WHERE id=%s",
                                 (f'{type(error).__name__}: response uncertain; look up the client order ID.',identifier))
                    conn.commit()
                    raise RuntimeError('Submission outcome UNKNOWN. No automatic retry. Use status and Alpaca dashboard.') from None
                conn.execute("""UPDATE public.astra_paper_tickets SET state='SUBMITTED',broker_order=%s,
                    last_checked_at=now() WHERE id=%s""",(Jsonb(remote),identifier))
                conn.commit()
                return remote
            finally:
                conn.rollback()
                conn.execute('SELECT pg_advisory_unlock(%s)',(GLOBAL_ORDER_LOCK,))
                conn.commit()
