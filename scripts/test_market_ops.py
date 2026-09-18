"""Offline tests. No network, brokerage, database or OpenAI side effects."""
from __future__ import annotations
import copy
import json
import sys
import types
import unittest
from datetime import datetime,date,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch,MagicMock
from uuid import uuid4

import pandas as pd
import requests

from src.us_market_ops import (Settings,NY,UTC,completed_sessions,plan_sync,features,wilder,
    validate_bar,quote_context,stamp,canonical,AlpacaHTTP,AlpacaReadError,PAPER_URL,DATA_URL,VERSION)
from src.paper_tickets import create_order,order_hash,money,preflight,TicketStore
from src.ops_review import payload_from_context

NOW=datetime(2026,9,18,15,0,tzinfo=UTC)


def sessions(n=270):
    return [v.date() for v in pd.bdate_range(end='2026-09-17',periods=n)]


def bars(n=270,mode='up'):
    result={}
    for i,d in enumerate(sessions(n)):
        p=100+i*.1 if mode=='up' else 200-i*.1 if mode=='down' else 100
        result[d]={'t':datetime.combine(d,datetime.min.time(),NY).isoformat(),'o':p,'h':p+1,'l':p-1,'c':p,'v':1000,'n':50,'vw':p}
    return result


def snapshot(age=1,bid=100,ask=100.1):
    return {'latestQuote':{'t':(NOW-timedelta(seconds=age)).isoformat(),'bp':bid,'ap':ask},
            'latestTrade':{'t':(NOW-timedelta(seconds=2)).isoformat(),'p':100},
            'dailyBar':{'o':99,'c':100,'v':100},'prevDailyBar':{'c':98,'v':500}}


def valid_inputs():
    return {'order':create_order('AAPL',1,100,95,110,'client1'),
            'account':{'id':'acct','status':'ACTIVE','currency':'USD','cash':'10000',
                       'trading_blocked':False,'account_blocked':False,'trade_suspended_by_user':False},
            'positions':[],'orders':[],
            'asset':{'status':'active','class':'us_equity','tradable':True},
            'clock':{'timestamp':NOW.isoformat(),'is_open':True},
            'calendar_today':[{'date':'2026-09-18','open':'09:30','close':'16:00'}],
            'live':quote_context(snapshot(),NOW,60,True),'settings':Settings(),'now':NOW}


class SettingsTests(unittest.TestCase):
    def test_default_feed(self): self.assertEqual(Settings().feed,'iex')
    def test_bad_feed(self):
        with self.assertRaises(ValueError): Settings(feed='delayed_sip')
    def test_bad_adjustment(self):
        with self.assertRaises(ValueError): Settings(adjustment='mystery')
    def test_bad_batch(self):
        with self.assertRaises(ValueError): Settings(batch_size=0)
    def test_bad_cap(self):
        with self.assertRaises(ValueError): Settings(max_order_usd=float('inf'))
    def test_naive_timestamp(self):
        with self.assertRaises(ValueError): stamp('2026-09-18T10:00:00')
    def test_z_timestamp(self): self.assertEqual(stamp('2026-09-18T15:00:00Z'),NOW)
    def test_nan_is_null(self): self.assertEqual(canonical({'x':float('nan')}),'{"x":null}')


class HistoryTests(unittest.TestCase):
    def test_current_calendar_day_excluded(self):
        cal=[{'date':'2026-09-17'},{'date':'2026-09-18'}]
        self.assertEqual(completed_sessions(cal,NOW),[date(2026,9,17)])
    def test_even_after_rth_current_day_excluded(self):
        now=NOW.replace(hour=23)
        self.assertEqual(completed_sessions([{'date':'2026-09-17'},{'date':'2026-09-18'}],now),[date(2026,9,17)])
    def test_weekend_prior_friday(self):
        now=datetime(2026,9,19,16,tzinfo=UTC)
        self.assertEqual(completed_sessions([{'date':'2026-09-18'}],now),[date(2026,9,18)])
    def test_empty_calendar_fails(self):
        with self.assertRaises(ValueError): completed_sessions([],NOW)
    def test_new_symbol_full(self):
        p=plan_sync({'X':{}},{},sessions(),NOW,Settings())
        self.assertTrue(p[0]['full'])
    def test_recent_skipped(self):
        p=plan_sync({'X':bars()},{'X':{'last_sync':NOW,'last_full_fetch':NOW}},sessions(),NOW,Settings())
        self.assertEqual(p,[])
    def test_missing_new_date_incremental(self):
        b=bars(); b.pop(max(b))
        p=plan_sync({'X':b},{'X':{'last_sync':NOW-timedelta(days=1),'last_full_fetch':NOW-timedelta(days=1)}},sessions(),NOW,Settings())
        self.assertFalse(p[0]['full']); self.assertEqual(p[0]['start'],sessions()[-6])
    def test_periodic_rebase(self):
        p=plan_sync({'X':bars()},{'X':{'last_sync':NOW,'last_full_fetch':NOW-timedelta(days=8)}},sessions(),NOW,Settings())
        self.assertTrue(p[0]['full'])
    def test_adopted_eventually_rebased(self):
        p=plan_sync({'X':bars()},{'X':{'last_sync':NOW,'first_managed_sync':NOW-timedelta(days=8)}},sessions(),NOW,Settings())
        self.assertTrue(p[0]['full'])
    def test_adopted_history_does_not_force_full(self):
        p=plan_sync({'X':bars()},{},sessions(),NOW,Settings())
        self.assertFalse(p[0]['full'])
    def test_incomplete_needs_history(self):
        p=plan_sync({'X':bars(50)},{},sessions(),NOW,Settings())
        self.assertTrue(p[0]['full'])
    def test_bar_negative(self):
        b=list(bars().values())[0]; b['c']=-1
        with self.assertRaises(ValueError): validate_bar(b)
    def test_bar_range(self):
        b=list(bars().values())[0]; b['h']=b['l']-1
        with self.assertRaises(ValueError): validate_bar(b)
    def test_bar_nan(self):
        b=list(bars().values())[0]; b['c']=float('nan')
        with self.assertRaises(ValueError): validate_bar(b)
    def test_rsi_up(self): self.assertEqual(features(bars(),sessions()[-1],sessions())['rsi_14'],100)
    def test_rsi_down(self): self.assertEqual(features(bars(mode='down'),sessions()[-1],sessions())['rsi_14'],0)
    def test_rsi_flat(self): self.assertEqual(features(bars(mode='flat'),sessions()[-1],sessions())['rsi_14'],50)
    def test_missing_session_fails(self):
        b=bars(); del b[sessions()[-50]]
        with self.assertRaises(ValueError): features(b,sessions()[-1],sessions())
    def test_short_history_fails(self):
        with self.assertRaises(ValueError): features(bars(60),sessions()[-1],sessions())
    def test_sma_uses_full_window(self):
        f=features(bars(),sessions()[-1],sessions())
        self.assertAlmostEqual(f['sma_200'],sum(100+i*.1 for i in range(70,270))/200)
    def test_wilder_seed(self):
        r=wilder(pd.Series(range(1,18)),14)
        self.assertTrue(pd.isna(r.iloc[12])); self.assertAlmostEqual(r.iloc[13],7.5)
        self.assertAlmostEqual(r.iloc[14],(7.5*13+15)/14)
    def test_data_not_mutated(self):
        b=bars(); original=copy.deepcopy(b); features(b,sessions()[-1],sessions()); self.assertEqual(b,original)


class SnapshotTests(unittest.TestCase):
    def test_fresh(self): self.assertTrue(quote_context(snapshot(),NOW,60,True)['quote_fresh'])
    def test_stale(self): self.assertFalse(quote_context(snapshot(age=100),NOW,60,True)['quote_fresh'])
    def test_future(self): self.assertFalse(quote_context(snapshot(age=-30),NOW,60,True)['quote_fresh'])
    def test_crossed(self): self.assertFalse(quote_context(snapshot(bid=101,ask=100),NOW,60,True)['quote_fresh'])
    def test_zero_bid(self): self.assertFalse(quote_context(snapshot(bid=0),NOW,60,True)['quote_fresh'])
    def test_closed_market(self): self.assertFalse(quote_context(snapshot(),NOW,60,False)['executable_quote_check'])
    def test_empty(self): self.assertFalse(quote_context({},NOW,60,True)['quote_fresh'])
    def test_trade_does_not_make_quote_fresh(self):
        self.assertFalse(quote_context(snapshot(age=900),NOW,60,True)['quote_fresh'])
    def test_partial_volume_not_called_rvol(self):
        self.assertNotIn('relative_volume',quote_context(snapshot(),NOW,60,True))


class RequestTests(unittest.TestCase):
    def client(self,responses):
        session=MagicMock(); session.headers={}; session.get.side_effect=responses
        return AlpacaHTTP(session=session,sleep=lambda _:None,pace=0),session
    def resp(self,status,payload):
        r=MagicMock();r.status_code=status;r.headers={};r.json.return_value=payload;return r
    def test_paper_host(self):
        c,s=self.client([self.resp(200,{})]);c.get('/v2/account',trading=True)
        self.assertTrue(s.get.call_args.args[0].startswith(PAPER_URL))
        self.assertFalse(s.get.call_args.kwargs['allow_redirects'])
    def test_reject_redirect(self):
        c,s=self.client([self.resp(302,{})])
        with self.assertRaises(AlpacaReadError): c.get('/v2/account',trading=True)
        self.assertEqual(s.get.call_count,1)
    def test_retry_read_429(self):
        c,s=self.client([self.resp(429,{}),self.resp(200,{'ok':1})])
        self.assertEqual(c.get('/v2/stocks/bars'),{'ok':1})
        self.assertEqual(s.get.call_count,2)
    def test_no_retry_permission_error(self):
        c,s=self.client([self.resp(403,{})])
        with self.assertRaises(AlpacaReadError): c.get('/v2/stocks/bars')
        self.assertEqual(s.get.call_count,1)
    def test_bounded_transport_failure(self):
        c,s=self.client([requests.Timeout()]*4)
        with self.assertRaises(AlpacaReadError): c.get('/v2/stocks/bars')
        self.assertEqual(s.get.call_count,4)
    def test_pagination(self):
        c,s=self.client([self.resp(200,{'bars':{'X':[{'n':1}]},'next_page_token':'p2'}),
                         self.resp(200,{'bars':{'X':[{'n':2}]},'next_page_token':None})])
        result=c.bars(['X'],date(2026,1,1),date(2026,1,3),Settings())
        self.assertEqual(len(result['X']),2)
        self.assertEqual(s.get.call_count,2)
    def test_repeated_page_rejected(self):
        c,s=self.client([self.resp(200,{'bars':{},'next_page_token':'same'})]*2)
        with self.assertRaises(AlpacaReadError): c.bars(['X'],date(2026,1,1),date(2026,1,3),Settings())
    def test_malformed_bars_not_empty_success(self):
        c,s=self.client([self.resp(200,{'oops':[]})])
        with self.assertRaises(AlpacaReadError): c.bars(['X'],date(2026,1,1),date(2026,1,3),Settings())


class PaperChecksTests(unittest.TestCase):
    def test_valid(self): self.assertEqual(preflight(**valid_inputs())['notional_usd'],'100')
    def test_noninteger_quantity(self):
        with self.assertRaises(ValueError): create_order('X',1.5,100,95,110,'x')
    def test_bool_quantity(self):
        with self.assertRaises(ValueError): create_order('X',True,100,95,110,'x')
    def test_bad_stop(self):
        with self.assertRaises(ValueError): create_order('X',1,100,101,110,'x')
    def test_bad_price_precision(self):
        with self.assertRaises(ValueError): money('10.001')
    def test_nan_price(self):
        with self.assertRaises(ValueError): money('NaN')
    def test_hash_binds_qty(self):
        a=create_order('X',1,100,95,110,'x');b=copy.deepcopy(a);b['qty']='2'
        self.assertNotEqual(order_hash(a),order_hash(b))
    def test_invalid_symbol_path(self):
        with self.assertRaises(ValueError): create_order('../orders',1,100,95,110,'x')
    def test_blocked(self):
        x=valid_inputs();x['account']['trading_blocked']=True
        with self.assertRaises(ValueError): preflight(**x)
    def test_unknown_permissions(self):
        x=valid_inputs();del x['account']['account_blocked']
        with self.assertRaises(ValueError): preflight(**x)
    def test_no_margin(self):
        x=valid_inputs();x['account']['cash']='0';x['account']['buying_power']='400000'
        with self.assertRaises(ValueError): preflight(**x)
    def test_reserves_pending_buys(self):
        x=valid_inputs();x['account']['cash']='150';x['orders']=[{'symbol':'Y','side':'buy','qty':'10','filled_qty':'0','limit_price':'10'}]
        with self.assertRaises(ValueError): preflight(**x)
    def test_uncertain_buy_cost_fails(self):
        x=valid_inputs();x['orders']=[{'symbol':'Y','side':'buy','qty':'1','filled_qty':'0','type':'market'}]
        with self.assertRaises(ValueError): preflight(**x)
    def test_duplicate_position(self):
        x=valid_inputs();x['positions']=[{'symbol':'AAPL','qty':'1'}]
        with self.assertRaises(ValueError): preflight(**x)
    def test_duplicate_order(self):
        x=valid_inputs();x['orders']=[{'symbol':'AAPL','side':'buy'}]
        with self.assertRaises(ValueError): preflight(**x)
    def test_closed(self):
        x=valid_inputs();x['clock']['is_open']=False
        with self.assertRaises(ValueError): preflight(**x)
    def test_early_close(self):
        x=valid_inputs();x['now']=NOW.replace(hour=19);x['clock']['timestamp']=x['now'].isoformat();x['calendar_today'][0]['close']='13:00'
        with self.assertRaises(ValueError): preflight(**x)
    def test_big_spread(self):
        x=valid_inputs();x['live']['spread_bps']=51
        with self.assertRaises(ValueError): preflight(**x)
    def test_stale_quote(self):
        x=valid_inputs();x['live']['executable_quote_check']=False
        with self.assertRaises(ValueError): preflight(**x)
    def test_old_entry_drift(self):
        x=valid_inputs();x['live']['midpoint']=120
        with self.assertRaises(ValueError): preflight(**x)
    def test_cap(self):
        x=valid_inputs();x['settings']=Settings(max_order_usd=50)
        with self.assertRaises(ValueError): preflight(**x)
    def test_non_us_asset(self):
        x=valid_inputs();x['asset']['class']='crypto'
        with self.assertRaises(ValueError): preflight(**x)


class ResponseRow:
    def __init__(self,row=None):self.row=row
    def fetchone(self):return self.row


class FakeConnection:
    def __init__(self,ticket):self.ticket=ticket;self.commits=0;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def commit(self):self.commits+=1
    def rollback(self):pass
    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if 'pg_try_advisory_lock' in sql:return ResponseRow({'locked':True})
        if 'FOR UPDATE' in sql:return ResponseRow(copy.deepcopy(self.ticket))
        if "SELECT id FROM public.astra_paper_tickets WHERE state" in sql:return ResponseRow()
        if "SET state='SUBMITTING'" in sql:self.ticket['state']='SUBMITTING'
        if "SET state='UNKNOWN'" in sql:self.ticket['state']='UNKNOWN'
        if "SET state='SUBMITTED'" in sql:self.ticket['state']='SUBMITTED'
        return ResponseRow()


@patch.dict('os.environ', {'ASTRA_ENABLE_PAPER_SUBMISSION': 'true'})
class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.order=create_order('AAPL',1,100,95,110,'id1')
        self.ticket={'id':uuid4(),'state':'PREPARED','order_payload':self.order,'order_sha256':order_hash(self.order),
                     'account_id':'acct','client_order_id':'id1','symbol':'AAPL','submit_before':datetime.now(UTC)+timedelta(minutes=5)}
        self.conn=FakeConnection(self.ticket);self.store=TicketStore()
        self.store.ticket=lambda _:copy.deepcopy(self.ticket);self.store.connect=lambda:self.conn
        self.api=MagicMock();self.api.session.post.return_value.status_code=200
        self.api.session.post.return_value.json.return_value={'id':'r1','symbol':'AAPL','client_order_id':'id1','status':'new'}
        fake=types.ModuleType('psycopg.types.json');fake.Jsonb=lambda x:x
        self.mods=patch.dict(sys.modules,{'psycopg.types.json':fake});self.mods.start()
        self.checks=patch('src.paper_tickets.get_checks',return_value=({'id':'acct'},{}));self.checks.start()
    def tearDown(self):self.checks.stop();self.mods.stop()
    def approve(self,_):return 'APPROVE PAPER '+str(self.ticket['id'])
    def test_submission(self):
        result=self.store.submit(self.api,Settings(),self.ticket['id'],ask=self.approve,ack_earnings_unknown=True)
        self.assertEqual(result['id'],'r1');self.assertEqual(self.api.session.post.call_count,1)
        self.assertEqual(self.ticket['state'],'SUBMITTED')
        self.assertEqual(self.api.session.post.call_args.args[0],PAPER_URL+'/v2/orders')
    def test_human_refusal(self):
        with self.assertRaises(ValueError):self.store.submit(self.api,Settings(),self.ticket['id'],ask=lambda _:'NO',ack_earnings_unknown=True)
        self.api.session.post.assert_not_called()
    def test_earnings_gap_not_silently_ignored(self):
        with self.assertRaises(ValueError):self.store.submit(self.api,Settings(),self.ticket['id'],ask=self.approve)
        self.api.session.post.assert_not_called()
    def test_expired(self):
        self.ticket['submit_before']=datetime.now(UTC)-timedelta(seconds=1)
        with self.assertRaises(ValueError):self.store.submit(self.api,Settings(),self.ticket['id'],ask=self.approve,ack_earnings_unknown=True)
        self.api.session.post.assert_not_called()
    def test_mutated_payload(self):
        self.ticket['order_payload']['qty']='2'
        with self.assertRaises(ValueError):self.store.submit(self.api,Settings(),self.ticket['id'],ask=self.approve,ack_earnings_unknown=True)
        self.api.session.post.assert_not_called()
    def test_payload_change_while_approving(self):
        def changed(_):
            self.ticket['order_payload']['qty']='2'
            self.ticket['order_sha256']=order_hash(self.ticket['order_payload'])
            return self.approve('')
        with self.assertRaises(ValueError):
            self.store.submit(self.api,Settings(),self.ticket['id'],ask=changed,ack_earnings_unknown=True)
        self.api.session.post.assert_not_called()
    def test_account_change_while_approving(self):
        def changed(_):
            self.ticket['account_id']='different'
            return self.approve('')
        with self.assertRaises(ValueError):
            self.store.submit(self.api,Settings(),self.ticket['id'],ask=changed,ack_earnings_unknown=True)
        self.api.session.post.assert_not_called()
    def test_timeout_unknown_no_retry(self):
        def timeout(*args,**kw):
            self.assertGreaterEqual(self.conn.commits,1)
            self.assertEqual(self.ticket['state'],'SUBMITTING')
            raise requests.Timeout()
        self.api.session.post.side_effect=timeout
        with self.assertRaises(RuntimeError):self.store.submit(self.api,Settings(),self.ticket['id'],ask=self.approve,ack_earnings_unknown=True)
        self.assertEqual(self.api.session.post.call_count,1);self.assertEqual(self.ticket['state'],'UNKNOWN')
    def test_unknown_never_resubmits(self):
        self.ticket['state']='UNKNOWN';self.store.reconcile=MagicMock(return_value=(self.ticket,None))
        self.store.submit(self.api,Settings(),self.ticket['id'])
        self.api.session.post.assert_not_called();self.store.reconcile.assert_called_once()
    def test_submitted_never_resubmits(self):
        self.ticket['state']='SUBMITTED';self.store.reconcile=MagicMock(return_value=(self.ticket,{'id':'x'}))
        self.store.submit(self.api,Settings(),self.ticket['id'])
        self.api.session.post.assert_not_called()


class ContextTests(unittest.TestCase):
    def context(self):
        return {'version':VERSION,'context_id':str(uuid4()),'captured_at':NOW.isoformat(),'limitations':[],
                'account':{},'positions':[],'open_orders':[],'market_clock':{},'feed':'iex','adjustment':'raw',
                'screened_count':100,'universe_count':500,'candidates':[{'symbol':'AAPL'}]}
    def test_current(self):
        self.assertEqual(payload_from_context(self.context(),now=NOW)['ops_version'],VERSION)
    def test_stale(self):
        with self.assertRaises(ValueError):payload_from_context(self.context(),now=NOW+timedelta(minutes=6))
    def test_future(self):
        with self.assertRaises(ValueError):payload_from_context(self.context(),now=NOW-timedelta(minutes=1))
    def test_empty(self):
        c=self.context();c['candidates']=[]
        with self.assertRaises(ValueError):payload_from_context(c,now=NOW)
    def test_duplicate(self):
        c=self.context();c['candidates']*=2
        with self.assertRaises(ValueError):payload_from_context(c,now=NOW)
    def test_version(self):
        c=self.context();c['version']='old'
        with self.assertRaises(ValueError):payload_from_context(c,now=NOW)


if __name__=='__main__':
    unittest.main(verbosity=2)
