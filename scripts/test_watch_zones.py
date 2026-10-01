import json
import unittest

from src.astra_review import validate_review
from src.watch_zones import reference_levels, watch_state


class WatchZoneTests(unittest.TestCase):
    def candidate(self):
        return {
            'symbol':'TEST',
            'quantitative':{
                'price':100.0,'atr_14':4.0,'sma_20':98.0,'sma_50':95.0,'sma_200':80.0,
                'high_20':110.0,'low_20':90.0,
            },
            'live_market':{
                'midpoint':102.0,'last_trade':102.1,'bid':101.9,'ask':102.1,
                'quote_fresh':True,'regular_market_open':True,'quote_timestamp':'2026-09-24T18:00:00+00:00',
                'quote_age_seconds':1.0,'spread_bps':19.6,
                'snapshot':{
                    'dailyBar':{'o':100,'h':104,'l':99,'c':102,'vw':101.5},
                    'prevDailyBar':{'c':99.5},
                }
            }
        }

    def test_reference_levels(self):
        levels=reference_levels(self.candidate())
        self.assertEqual(levels['current_reference_price'],102.0)
        self.assertEqual(levels['atr_14'],4.0)
        self.assertIn(98.0, levels['support_references'])
        self.assertIn(110.0, levels['resistance_references'])

    def test_watch_trigger(self):
        ev={'watch_buy_zone_low':100,'watch_buy_zone_high':103,'watch_breakout_trigger':110}
        live=self.candidate()['live_market']
        self.assertEqual(watch_state(ev,live)['state'],'BUY_ZONE_PRICE_TRIGGER')

    def test_watch_review_valid(self):
        payload={'max_picks':1,'candidates':[{'symbol':'TEST','recent_news':[]}]}
        report={
            'market_summary':'x','coverage_limitations':[],'selected_symbols':[],
            'evaluations':[{
                'symbol':'TEST','decision':'WATCH','strength':'medium','setup_type':'PULLBACK_IN_UPTREND',
                'thesis':'wait','bull_case':'bull','bear_case':'bear','risks':[],'invalidation':'invalid',
                'entry_rationale':'wait for pullback','entry_price':None,'stop_price':None,'target_price':None,
                'expected_holding_days':None,'time_stop_days':None,'exit_rule':'monitor',
                'risk_tier':None,'suggested_quantity':None,
                'watch_buy_zone_low':98.0,'watch_buy_zone_high':100.0,'watch_breakout_trigger':105.0,
                'watch_stop_zone_low':94.0,'watch_stop_zone_high':95.0,'watch_target_1':108.0,
                'watch_target_2':112.0,'watch_trigger_condition':'support holds and momentum stabilizes',
                'watch_expires_after_sessions':5,'evidence_ids':[],'missing_information':[]
            }],
            'additional_research':[]
        }
        out=validate_review(json.dumps(report),payload)
        self.assertEqual(out.evaluations[0].decision,'WATCH')

    def test_buy_cannot_carry_watch_zone(self):
        payload={'max_picks':1,'sizing_policy':{'strategy_capital_usd':None},'candidates':[{'symbol':'TEST','recent_news':[]}]}
        report={
            'market_summary':'x','coverage_limitations':[],'selected_symbols':['TEST'],
            'evaluations':[{
                'symbol':'TEST','decision':'BUY','strength':'medium','setup_type':'PULLBACK_IN_UPTREND',
                'thesis':'buy','bull_case':'bull','bear_case':'bear','risks':[],'invalidation':'invalid',
                'entry_rationale':'entry','entry_price':100.0,'stop_price':95.0,'target_price':110.0,
                'expected_holding_days':5,'time_stop_days':5,'exit_rule':'exit','risk_tier':'medium',
                'suggested_quantity':None,'watch_buy_zone_low':98.0,'watch_buy_zone_high':100.0,
                'watch_breakout_trigger':None,'watch_stop_zone_low':None,'watch_stop_zone_high':None,
                'watch_target_1':None,'watch_target_2':None,'watch_trigger_condition':'','watch_expires_after_sessions':None,
                'evidence_ids':[],'missing_information':[]
            }],'additional_research':[]
        }
        with self.assertRaises(ValueError):
            validate_review(json.dumps(report),payload)


if __name__=='__main__':
    unittest.main()
