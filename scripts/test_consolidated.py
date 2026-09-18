"""Regression tests specific to this repo consolidation. Synthetic/local only."""
from __future__ import annotations
import copy
import inspect
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.project_health import REQUIRED, check_columns
from src.profit_tracking import goal_plan, paper_profit_report
from src.pnl_tracker import PnLTracker
from src.us_market_ops import Settings, plan_sync, sync_history, AlpacaHTTP, AlpacaReadError
from src.research_engine import CostPolicy, enforce_budget, BudgetStore
from scripts.trader import main, build_parser
from scripts.test_market_ops import bars, sessions, NOW
from scripts.test_profit_tracking import fixture, CREATED

class GoalTests(unittest.TestCase):
    def test_no_capital_not_guessed_from_margin(self):
        self.assertIsNone(goal_plan()['allocated_capital_usd'])
    def test_costs_unknown_not_zero(self):
        self.assertIsNone(goal_plan(5000)['required_return_on_allocated_capital_pct'])
    def test_explicit_costs(self):
        self.assertEqual(goal_plan(5000,costs=1)['required_return_on_allocated_capital_pct'], ['2.02','4.02'])
    def test_zero_capital_rejected(self):
        with self.assertRaises(ValueError): goal_plan(0)
    def test_nonfinite(self):
        for v in ('NaN','Infinity',True):
            with self.subTest(value=v),self.assertRaises(ValueError): goal_plan(v)
    def test_bad_period(self):
        with self.assertRaises(ValueError): goal_plan(5000,days=1)
    def test_bad_range(self):
        with self.assertRaises(ValueError): goal_plan(5000,low=200,high=100)
    def test_does_not_depend_on_broker_or_model(self):
        self.assertNotIn('AstraReviewer',inspect.getsource(goal_plan))
        self.assertNotIn('submit',inspect.getsource(goal_plan))

class LedgerEdgeTests(unittest.TestCase):
    def calc(self,rows=None):
        return PnLTracker.calculate(rows or fixture(), [], account_created_at=CREATED,
            as_of=NOW, history_complete=True, external_costs_usd=2)
    def test_return_of_capital_not_ignored(self):
        r=self.calc(fixture()+[{'id':'roc','activity_type':'DIVROC','date':'2026-09-10','net_amount':'3'}])
        self.assertFalse(r['complete']);self.assertIsNone(r['realized_gross_usd'])
    def test_activity_before_creation_invalidates(self):
        rows=fixture();rows[0]['transaction_time']='2026-07-01T15:00:00Z'
        self.assertFalse(self.calc(rows)['complete'])
    def test_short_trade_no_profit_claim(self):
        self.assertFalse(self.calc(fixture()[1:])['complete'])
    def test_report_only_get_requests(self):
        api=MagicMock()
        account={'id':'paper-id','created_at':CREATED,'currency':'USD'}
        api.get.side_effect=[account,fixture(),[],account]
        with patch('src.profit_tracking.utcnow',return_value=NOW):
            r=paper_profit_report(api,days=14,capital=5000,external_costs=2)
        self.assertEqual(r['net_realized_after_known_costs_usd'],'72.00')
        self.assertEqual(r['goal_status'],'below');api.session.post.assert_not_called()
    def test_report_unknown_costs_unknown_goal(self):
        api=MagicMock();a={'id':'paper-id','created_at':CREATED,'currency':'USD'}
        api.get.side_effect=[a,fixture(),[],a]
        with patch('src.profit_tracking.utcnow',return_value=NOW):r=paper_profit_report(api)
        self.assertEqual(r['goal_status'],'unavailable')

class CLIContractTests(unittest.TestCase):
    def test_help_local(self):
        self.assertIn('review',build_parser().format_help())
    def test_goal_calls_no_api_or_database(self):
        with patch('src.us_market_ops.AlpacaHTTP') as api,patch('src.project_health.connect') as conn:
            self.assertEqual(main(['goal','--capital','5000','--costs','0']),0)
        api.assert_not_called();conn.assert_not_called()
    def test_review_send_not_default(self):
        args=build_parser().parse_args(['review','--context','00000000-0000-0000-0000-000000000001'])
        self.assertFalse(args.send)
    def test_resume_requires_existing_review_id(self):
        args=build_parser().parse_args(['resume','--review','00000000-0000-0000-0000-000000000001'])
        self.assertEqual(str(args.review),'00000000-0000-0000-0000-000000000001')
    def test_reconcile_is_local_command(self):
        args=build_parser().parse_args(['reconcile','--review','00000000-0000-0000-0000-000000000001',
                                        '--cost-low','2.00','--cost-high','2.05','--reason','fixture'])
        self.assertEqual(args.command,'reconcile')
    def test_report_maps_exact_id_flag(self):
        with patch('scripts.trader.delegate',return_value=0) as d:
            main(['report','--review','00000000-0000-0000-0000-000000000001'])
        self.assertEqual(d.call_args.args[1][0],'--id')
    def test_broad_paid_runner_blocked_before_db(self):
        import scripts.run_astra_review as legacy
        with patch.object(sys,'argv',['legacy','--send']),patch.object(legacy,'ReviewStore') as store:
            self.assertEqual(legacy.main(),2)
        store.assert_not_called()
    def test_legacy_executor_disabled(self):
        from src.trade_manager import TradeManager
        with self.assertRaises(RuntimeError):TradeManager().execute_approved_trade(1,500)
    def test_current_runner_delegates_budget(self):
        from src.ops_review import review_context
        with patch('src.research_engine.run_review',return_value=1) as run:
            self.assertEqual(review_context(None,{},'gpt-6-astra',True),1)
        self.assertTrue(run.call_args.kwargs['send'])
    def test_paper_off_without_opt_in(self):
        from src.paper_tickets import TicketStore
        adapter=types.ModuleType('psycopg.types.json');adapter.Jsonb=lambda x:x
        with patch.dict(sys.modules,{'psycopg.types.json':adapter}),patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'disabled'):TicketStore().submit(MagicMock(),Settings(),'id')
    def test_budget_blocks_old_unresolved(self):
        old={'id':'unknown','started_at':NOW-timedelta(days=10),'status':'UNKNOWN',
             'cost_high_usd':Decimal('.3'),'input_payload':{}}
        with self.assertRaisesRegex(ValueError,'unresolved'):enforce_budget([old],CostPolicy(),Decimal('.3'),NOW)
    def test_query_includes_unresolved_old_attempts(self):
        conn=MagicMock();BudgetStore._rows(conn)
        self.assertIn("OR r.status IN",conn.execute.call_args.args[0])

class SchemaTests(unittest.TestCase):
    def rows(self):
        return [{'table_name':t,'column_name':c,'udt_name':k} for t,cols in REQUIRED.items() for c,k in cols.items()]
    def test_type_check_not_just_count(self):
        conn=MagicMock();conn.execute.return_value.fetchall.return_value=self.rows()
        self.assertEqual(check_columns(conn),[])
    def test_missing_column_detected(self):
        rows=self.rows(); rows=[r for r in rows if r['column_name']!='scan_id']
        conn=MagicMock();conn.execute.return_value.fetchall.return_value=rows
        self.assertTrue(any('scan_id' in p for p in check_columns(conn)))
    def test_wrong_type_detected(self):
        rows=self.rows(); rows[0]['udt_name']='int8'
        conn=MagicMock();conn.execute.return_value.fetchall.return_value=rows
        self.assertTrue(check_columns(conn))

class IncrementalTests(unittest.TestCase):
    def test_gap_retries_after_daily_refresh(self):
        b=bars();del b[sessions()[-40]]
        plans=plan_sync({'X':b},{'X':{'last_sync':NOW-timedelta(days=2),'last_full_fetch':NOW-timedelta(days=2)}},
                        sessions(),NOW,Settings())
        self.assertLessEqual(plans[0]['start'],sessions()[-40])
    def test_setting_bad_refresh_period(self):
        with self.assertRaises(ValueError):Settings(full_refresh_days=0)
    def test_setting_full_window_overflow(self):
        with self.assertRaises(ValueError):Settings(backfill_sessions=10000)
    def test_history_groups_different_windows(self):
        api=MagicMock();store=MagicMock();api.requests_made=0
        api.calendar.return_value=[{'date':d.isoformat()} for d in sessions()]
        store.load_cache.return_value=({'A':bars(),'B':{}},{'A':{'last_sync':NOW-timedelta(days=1),'last_full_fetch':NOW}})
        api.bars.side_effect=lambda syms,start,end,settings: {s:list(bars().values()) for s in syms}
        with patch('src.us_market_ops.utcnow',return_value=NOW):
            self.assertEqual(sync_history(api,store,['A','B'],Settings()),[])
        self.assertEqual(api.bars.call_count,2)
        self.assertTrue(all(len(c.args[0])==1 for c in api.bars.call_args_list))
    def test_one_connection_per_batch_not_per_bar(self):
        from src.us_market_ops import OpsStore
        src=inspect.getsource(OpsStore.save_group)
        self.assertEqual(src.count('self.connect()'),1)
        self.assertIn('executemany',src)
        self.assertIn('IS DISTINCT FROM',src)
    def test_malformed_news_is_error(self):
        client=object.__new__(AlpacaHTTP);client.get=MagicMock(return_value={})
        with self.assertRaises(AlpacaReadError):client.news('AAPL',NOW)

if __name__=='__main__':
    unittest.main(verbosity=2)
