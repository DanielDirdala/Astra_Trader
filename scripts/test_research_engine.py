"""Offline tests only. Every network/database call below is mocked."""
from __future__ import annotations
import copy
import json
import sys
import types
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.research_engine import (CostPolicy, compact_live, compact_news, build_finalist_input,
    economical_spec, count_input_tokens, call_allowance, budget_snapshot, enforce_budget,
    validate_send_freshness, BudgetStore, run_review)
from src.astra_review import request_fingerprint, usage_estimate, validate_review
from src.us_market_ops import VERSION
from src.profit_tracking import goal_plan

def goal_returns(capital, operating_cost=0):
    return tuple(float(v) for v in goal_plan(capital, costs=operating_cost)['required_return_on_allocated_capital_pct'])


NOW = datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc)


def article(symbol, index=1, headline=None):
    return {'source_id': f'NEWS:{symbol}:{index}', 'published_at': (NOW-timedelta(hours=index)).isoformat(),
            'headline': headline or f'Article {index}', 'summary': 'Evidence, not advice.',
            'source': 'Fixture', 'url': f'https://example.test/{symbol}/{index}'}


def candidate(symbol='AAA', sector='Tech', score=10):
    return {'symbol': symbol, 'sector': sector, 'industry': None,
        'quantitative': {'price': 100., 'atr_pct': 2., 'technical_score': score,
                        'session_date': '2026-09-17', 'history_provenance': ['fixture']},
        'news_fetch_status': 'ok', 'recent_news': [article(symbol, i) for i in range(1, 6)],
        'live_market': {'quote_timestamp': NOW.isoformat(), 'bid': 100., 'ask': 100.1,
                        'spread_bps': 10., 'quote_fresh': True,
                        'snapshot': {'minuteBar': {'t': NOW.isoformat(), 'c': 100., 'v': 10},
                                     'latestQuote': {'bp': 100., 'ap': 100.1}}},
        'market_context': {'SPY': {'daily': {'price': 500.}, 'live': {'snapshot': {}}}},
        'earnings_calendar': {'status': 'not_connected'}, 'social_signals': {'status': 'not_connected'}}


def context():
    return {'context_id': str(uuid4()), 'version': VERSION, 'captured_at': NOW.isoformat(),
        'limitations': ['fixture research data'], 'account': {'cash': '1000'},
        'positions': [], 'open_orders': [], 'market_clock': {'is_open': True, 'timestamp': NOW.isoformat()},
        'feed': 'iex', 'adjustment': 'raw', 'screened_count': 500, 'universe_count': 505,
        'daily_target_session': '2026-09-17',
        'candidates': [candidate('AAA', 'Tech', 10), candidate('BBB', 'Tech', 9),
                       candidate('CCC', 'Tech', 8), candidate('DDD', 'Health Care', 7),
                       candidate('EEE', 'Industrials', 6)]}


def row(cost='0.20', status='COMPLETED', hours=24, reservation=None):
    return {'id': uuid4(), 'status': status, 'started_at': NOW-timedelta(hours=hours),
            'cost_high_usd': Decimal(cost) if cost is not None else None,
            'input_payload': {} if reservation is None else {'budget_guard': {'reservation_usd': reservation}}}


class PolicyTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual((CostPolicy().finalists, CostPolicy().max_output_tokens), (3, 3000))
    def test_invalid_finalists(self):
        with self.assertRaises(ValueError): CostPolicy(finalists=50)
    def test_invalid_bool(self):
        with self.assertRaises(ValueError): CostPolicy(finalists=True)
    def test_invalid_money(self):
        with self.assertRaises(ValueError): CostPolicy(per_call_usd=Decimal('NaN'))
    def test_picks_bounded(self):
        with self.assertRaises(ValueError): CostPolicy(finalists=1, max_picks=2)
    def test_env(self):
        with patch.dict('os.environ', {'ASTRA_FINALISTS': '4', 'ASTRA_BUDGET_7D_USD': '0.90'}, clear=True):
            self.assertEqual(CostPolicy.load().rolling_7d_usd, Decimal('.90'))


class PayloadTests(unittest.TestCase):
    def build(self, ctx=None): return build_finalist_input(ctx or context(), CostPolicy(), NOW)
    def test_top_three_sector_cap(self):
        payload, _ = self.build()
        self.assertEqual([c['symbol'] for c in payload['candidates']], ['AAA', 'BBB', 'DDD'])
    def test_benchmark_once(self):
        p, _ = self.build()
        self.assertIn('SPY', p['shared_market_context'])
        self.assertTrue(all('market_context' not in c for c in p['candidates']))
    def test_no_mutation(self):
        ctx=context(); before=copy.deepcopy(ctx); self.build(ctx); self.assertEqual(ctx, before)
    def test_snapshot_keeps_minute_bar(self):
        p, _=self.build(); live=p['candidates'][0]['live_market']
        self.assertNotIn('snapshot', live); self.assertEqual(live['bars']['minuteBar']['c'], 100.)
    def test_positions_not_new_entries(self):
        c=context(); c['positions']=[{'symbol': 'AAA'}]
        p,a=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']]); self.assertIn('AAA',a['excluded'])
    def test_pending_orders_not_new_entries(self):
        c=context(); c['open_orders']=[{'symbol': 'AAA'}]
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_stale_quote_excluded(self):
        c=context(); c['candidates'][0]['live_market']['quote_timestamp']=(NOW-timedelta(minutes=2)).isoformat()
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_bad_quote_excluded(self):
        c=context(); c['candidates'][0]['live_market']['ask']=99
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_missing_news_excluded(self):
        c=context(); c['candidates'][0]['news_fetch_status']='failed'
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_zero_news_not_failure(self):
        c=context(); c['candidates'][0]['recent_news']=[]
        p,_=self.build(c); self.assertEqual(p['candidates'][0]['recent_news'],[])
    def test_bad_daily_date_excluded(self):
        c=context(); c['candidates'][0]['quantitative']['session_date']='2026-09-01'
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_invalid_score_excluded(self):
        c=context(); c['candidates'][0]['quantitative']['technical_score']=None
        p,_=self.build(c); self.assertNotIn('AAA',[x['symbol'] for x in p['candidates']])
    def test_closed_market_research_allowed(self):
        c=context(); c['market_clock']['is_open']=False
        c['candidates'][0]['live_market']['quote_timestamp']=(NOW-timedelta(days=1)).isoformat()
        p,_=self.build(c); self.assertEqual(p['candidates'][0]['symbol'],'AAA')
    def test_no_candidates_no_forced_fill(self):
        c=context(); c['positions']=[{'symbol': x['symbol']} for x in c['candidates']]
        p,_=self.build(c); self.assertEqual(p['candidates'],[])
    def test_sector_cap_not_relaxed(self):
        c=context(); c['candidates']=[candidate('A','Tech'),candidate('B','Tech'),candidate('C','Tech')]
        p,_=self.build(c); self.assertEqual(len(p['candidates']),2)
    def test_stale_context(self):
        c=context(); c['captured_at']=(NOW-timedelta(minutes=10)).isoformat()
        with self.assertRaises(ValueError): self.build(c)
    def test_benchmark_mismatch(self):
        c=context(); c['candidates'][1]['market_context']['SPY']['daily']['price']=501
        with self.assertRaises(ValueError): self.build(c)
    def test_stable_fingerprint_same_capture(self):
        c=context(); p,_=build_finalist_input(c,CostPolicy(),NOW)
        q,_=build_finalist_input(c,CostPolicy(),NOW+timedelta(seconds=1))
        self.assertEqual(request_fingerprint(economical_spec(p,'gpt-6-astra',CostPolicy())),
                         request_fingerprint(economical_spec(q,'gpt-6-astra',CostPolicy())))
    def test_after_count_quote_rechecked(self):
        p,_=self.build()
        with self.assertRaises(ValueError): validate_send_freshness(p,CostPolicy(),NOW+timedelta(seconds=61))
    def test_original_paper_context_identifiers_preserved(self):
        c=context(); p,_=self.build(c)
        self.assertEqual(p['context_id'],c['context_id']); self.assertEqual(p['ops_version'], VERSION)
    def test_no_trade_goal_in_request(self):
        p,_=self.build(); s=economical_spec(p,'gpt-6-astra',CostPolicy())
        self.assertNotIn('target_profit',json.dumps(s)); self.assertNotIn('tools',s)
    def test_output_limit_and_low_reasoning(self):
        p,_=self.build(); s=economical_spec(p,'gpt-6-astra',CostPolicy())
        self.assertEqual(s['max_output_tokens'],3000); self.assertEqual(s['reasoning'],{'effort':'low'}); self.assertEqual(s['service_tier'],'flex'); self.assertTrue(s['background'])
    def test_model_not_silently_changed(self):
        p,_=self.build()
        with self.assertRaises(ValueError): economical_spec(p,'other-model',CostPolicy())


class NewsTests(unittest.TestCase):
    def test_cap_three(self):
        self.assertEqual(len(compact_news([article('AAA',i) for i in range(1,10)],3,NOW)),3)
    def test_latest_first(self):
        result=compact_news([article('AAA',3),article('AAA',1)],3,NOW)
        self.assertEqual(result[0]['source_id'],'NEWS:AAA:1')
    def test_dedup_headline(self):
        self.assertEqual(len(compact_news([article('AAA',1,'Same.'),article('AAA',2,'Same!')],3,NOW)),1)
    def test_future_news_removed(self):
        a=article('AAA'); a['published_at']=(NOW+timedelta(days=1)).isoformat()
        self.assertEqual(compact_news([a],3,NOW),[])
    def test_old_news_removed(self):
        a=article('AAA'); a['published_at']=(NOW-timedelta(days=8)).isoformat()
        self.assertEqual(compact_news([a],3,NOW),[])
    def test_truncation_marked(self):
        a=article('AAA'); a['summary']='x'*1000
        r=compact_news([a],3,NOW)[0]; self.assertTrue(r['text_truncated']); self.assertEqual(len(r['summary']),450)
    def test_negative_news_not_filtered(self):
        a=article('AAA',headline='Company announces investigation and losses')
        self.assertEqual(compact_news([a],3,NOW)[0]['headline'],a['headline'])


class CostTests(unittest.TestCase):
    def test_reservation(self): self.assertEqual(call_allowance(6000,CostPolicy()),Decimal('.123750'))
    def test_input_limit(self):
        with self.assertRaises(ValueError): call_allowance(8001,CostPolicy())
    def test_call_price_limit(self):
        with self.assertRaises(ValueError): call_allowance(6000,replace(CostPolicy(),per_call_usd=Decimal('.10')))
    def test_week_budget(self):
        with self.assertRaises(ValueError): enforce_budget([row('.80')],CostPolicy(),Decimal('.30'),NOW)
    def test_attempt_cap(self):
        with self.assertRaises(ValueError): enforce_budget([row(),row()],CostPolicy(),Decimal('.10'),NOW)
    def test_cooldown(self):
        with self.assertRaises(ValueError): enforce_budget([row(hours=1)],CostPolicy(),Decimal('.30'),NOW)
    def test_unknown_not_zero(self):
        with self.assertRaises(ValueError): enforce_budget([row(None)],CostPolicy(),Decimal('.30'),NOW)
    def test_unresolved_timeout(self):
        with self.assertRaises(ValueError): enforce_budget([row(None,'UNKNOWN',reservation='.33')],CostPolicy(),Decimal('.30'),NOW)
    def test_valid_budget(self):
        s=enforce_budget([row('.16')],CostPolicy(),Decimal('.30'),NOW); self.assertEqual(s['committed_usd'],Decimal('.16'))
    def test_incomplete_cost_counted(self):
        self.assertEqual(budget_snapshot([row('.20','INCOMPLETE')])['committed_usd'],Decimal('.20'))
    def test_reserved_started_counted(self):
        self.assertEqual(budget_snapshot([row(None,'STARTED',reservation='.33')])['committed_usd'],Decimal('.33'))
    def test_reasoning_not_double_counted(self):
        response={'model':'gpt-6-astra','usage':{'input_tokens':6000,'output_tokens':2000,
                  'output_tokens_details':{'reasoning_tokens':1500}}}
        self.assertEqual(usage_estimate(response)['cost_low_usd'],Decimal('.16'))
    def test_count_endpoint_only_supported_fields(self):
        fake=MagicMock(); fake.post.return_value.status_code=200; fake.post.return_value.json.return_value={'input_tokens':6000}
        p,_=build_finalist_input(context(),CostPolicy(),NOW); s=economical_spec(p,'gpt-6-astra',CostPolicy())
        self.assertEqual(count_input_tokens(s,'FAKE',fake),6000)
        sent=fake.post.call_args.kwargs['json']
        self.assertEqual(set(sent),{'model','instructions','input','reasoning','text'})
        self.assertNotIn('max_output_tokens',sent); self.assertEqual(fake.post.call_count,1)
    def test_count_failure_no_retry(self):
        fake=MagicMock(); fake.post.return_value.status_code=403
        p,_=build_finalist_input(context(),CostPolicy(),NOW); s=economical_spec(p,'gpt-6-astra',CostPolicy())
        with self.assertRaises(RuntimeError): count_input_tokens(s,'FAKE',fake)
        self.assertEqual(fake.post.call_count,1)
    def test_invalid_count(self):
        fake=MagicMock(); fake.post.return_value.status_code=200; fake.post.return_value.json.return_value={'input_tokens':True}
        p,_=build_finalist_input(context(),CostPolicy(),NOW)
        with self.assertRaises(ValueError): count_input_tokens(economical_spec(p,'gpt-6-astra',CostPolicy()),'FAKE',fake)


class RunnerTests(unittest.TestCase):
    def test_preview_makes_no_calls(self):
        counter=MagicMock(); requester=MagicMock(); reviews=MagicMock()
        with patch('src.research_engine.write_local',return_value='mock.json'):
            result=run_review(None,context(),now=NOW,counter=counter,requester=requester,reviews=reviews)
        self.assertEqual(result,0); counter.assert_not_called(); requester.assert_not_called(); reviews.check_tables.assert_not_called()
    def test_empty_finalists_no_paid_calls(self):
        c=context(); c['positions']=[{'symbol':s['symbol']} for s in c['candidates']]
        requester=MagicMock()
        with patch('src.research_engine.write_local',return_value='mock.json'):
            self.assertEqual(run_review(None,c,send=True,now=NOW,requester=requester),0)
        requester.assert_not_called()
    def test_existing_routes_redirect(self):
        from src.ops_review import review_context
        with patch('src.research_engine.run_review',return_value=0) as mocked:
            review_context('store','context','gpt-6-astra',False)
            mocked.assert_called_once()
    def test_claim_atomic_lock_and_no_migration(self):
        # Mock psycopg JSON adapter and the transaction; do not connect to PostgreSQL.
        j=types.ModuleType('psycopg.types.json'); j.Jsonb=lambda value:value
        conn=MagicMock(); conn.__enter__.return_value=conn
        def execute(sql, params=None):
            cursor=MagicMock()
            if 'SELECT clock_timestamp()' in sql: cursor.fetchone.return_value={'now':NOW}
            elif 'request_fingerprint=%s' in sql: cursor.fetchone.return_value=None
            elif 'FROM public.astra_review_runs r' in sql: cursor.fetchall.return_value=[]
            elif 'INSERT INTO public.system_events' in sql: cursor.fetchone.return_value={'id':1}
            elif 'INSERT INTO public.astra_review_runs' in sql: cursor.fetchone.return_value={'id':'new','status':'STARTED'}
            return cursor
        conn.execute.side_effect=execute
        reviews=MagicMock(); reviews.connect.return_value=conn
        p,_=build_finalist_input(context(),CostPolicy(),NOW); s=economical_spec(p,'gpt-6-astra',CostPolicy())
        with patch.dict(sys.modules,{'psycopg.types.json':j}):
            answer,created=BudgetStore(reviews).claim(p,s,'fingerprint',CostPolicy(),Decimal('.30'))
        self.assertTrue(created); self.assertEqual(answer['id'],'new')
        statements=[c.args[0] for c in conn.execute.call_args_list]
        self.assertIn('SET LOCAL lock_timeout',statements[0]); self.assertIn('pg_advisory_xact_lock',statements[1]); self.assertTrue(all('CREATE TABLE' not in q for q in statements))
        insertion=next(c for c in conn.execute.call_args_list if 'INSERT INTO public.astra_review_runs' in c.args[0])
        self.assertEqual(insertion.args[1][-1]['budget_guard']['reservation_usd'],'0.30')


class SendPathTests(unittest.TestCase):
    def mocks(self):
        reviews=MagicMock()
        conn=MagicMock(); conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value=None
        reviews.connect.return_value=conn
        return reviews

    def response(self, state='completed'):
        ctx=context(); payload,_=build_finalist_input(ctx,CostPolicy(),NOW)
        evaluations=[{'symbol':c['symbol'],'decision':'WATCH','strength':'low','thesis':'More evidence needed.',
                     'bull_case':'Momentum could persist.','bear_case':'Trend could reverse.',
                     'risks':['Unknown earnings.'],'invalidation':'Not an entry.',
                     'entry_price':None,'stop_price':None,'target_price':None,'expected_holding_days':None,
                     'evidence_ids':[],'missing_information':['Earnings date.']} for c in payload['candidates']]
        report={'market_summary':'Fixture only.','coverage_limitations':['Shortlist only.'],
                'selected_symbols':[],'evaluations':evaluations,'additional_research':[]}
        return {'id':'resp_fake','model':'gpt-6-astra','status':state,
                'usage':{'input_tokens':6000,'output_tokens':2000},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(report)}]}]}

    def test_completed_request_once(self):
        reviews=self.mocks(); reviews.capture_response.side_effect=lambda _id,res:usage_estimate(res)
        reviews.complete.return_value=[1,2,3]
        requester=MagicMock(return_value=self.response()); counter=MagicMock(return_value=6000)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fake'}), \
             patch('src.research_engine.utcnow',return_value=NOW), \
             patch('src.research_engine.write_local',return_value='mock.json'), \
             patch.object(BudgetStore,'recent',return_value=[]), \
             patch.object(BudgetStore,'claim',return_value=({'id':uuid4(),'status':'STARTED'},True)):
            code=run_review(None,context(),send=True,now=NOW,counter=counter,requester=requester,reviews=reviews)
        self.assertEqual(code,0); requester.assert_called_once(); counter.assert_called_once(); reviews.complete.assert_called_once()

    def test_incomplete_billed_without_retry_or_proposals(self):
        reviews=self.mocks(); reviews.capture_response.side_effect=lambda _id,res:usage_estimate(res)
        requester=MagicMock(return_value=self.response('incomplete'))
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fake'}), \
             patch('src.research_engine.utcnow',return_value=NOW), \
             patch('src.research_engine.write_local',return_value='mock.json'), \
             patch.object(BudgetStore,'recent',return_value=[]), \
             patch.object(BudgetStore,'claim',return_value=({'id':uuid4(),'status':'STARTED'},True)):
            code=run_review(None,context(),send=True,now=NOW,counter=lambda *_:6000,requester=requester,reviews=reviews)
        self.assertEqual(code,1); requester.assert_called_once(); reviews.complete.assert_not_called(); reviews.capture_response.assert_called_once()

    def test_unknown_request_never_retried(self):
        reviews=self.mocks(); requester=MagicMock(side_effect=TimeoutError('mock'))
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fake'}), \
             patch('src.research_engine.utcnow',return_value=NOW), \
             patch('src.research_engine.write_local',return_value='mock.json'), \
             patch.object(BudgetStore,'recent',return_value=[]), \
             patch.object(BudgetStore,'claim',return_value=({'id':uuid4(),'status':'STARTED'},True)):
            code=run_review(None,context(),send=True,now=NOW,counter=lambda *_:6000,requester=requester,reviews=reviews)
        self.assertEqual(code,1); requester.assert_called_once(); self.assertEqual(reviews.fail.call_args.args[1],'UNKNOWN')

    def test_duplicate_does_not_count_or_generate(self):
        reviews=self.mocks()
        reviews.connect.return_value.execute.return_value.fetchone.return_value={'id':'old','status':'COMPLETED'}
        requester=MagicMock(); counter=MagicMock()
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fake'}), patch('src.research_engine.write_local',return_value='mock.json'):
            code=run_review(None,context(),send=True,now=NOW,counter=counter,requester=requester,reviews=reviews)
        self.assertEqual(code,0); counter.assert_not_called(); requester.assert_not_called()

    def test_out_of_budget_never_counts_or_generates(self):
        reviews=self.mocks(); requester=MagicMock(); counter=MagicMock()
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fake'}), \
             patch('src.research_engine.utcnow',return_value=NOW), \
             patch('src.research_engine.write_local',return_value='mock.json'), \
             patch.object(BudgetStore,'recent',return_value=[row('1.02')]):
            with self.assertRaises(ValueError):
                run_review(None,context(),send=True,now=NOW,counter=counter,requester=requester,reviews=reviews)
        counter.assert_not_called(); requester.assert_not_called()


class ProfitArithmeticTests(unittest.TestCase):
    def test_five_thousand(self): self.assertEqual(goal_returns(5000),(2.,4.))
    def test_two_thousand(self): self.assertEqual(goal_returns(2000),(5.,10.))
    def test_cost_added(self): self.assertEqual(goal_returns(10000,operating_cost=1),(1.01,2.01))
    def test_invalid_capital(self):
        with self.assertRaises(ValueError): goal_returns(0)
    def test_invalid_cost(self):
        with self.assertRaises(ValueError): goal_returns(1000,operating_cost=-1)


if __name__=='__main__':
    unittest.main(verbosity=2)
