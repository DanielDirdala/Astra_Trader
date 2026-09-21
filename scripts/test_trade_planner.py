"""Offline tests for v0.4 finalist quality and deterministic sizing."""
import unittest
from decimal import Decimal

from src.finalist_quality import analyze_candidate, exclusion_reason
from src.trade_planner import SizingPolicy, build_trade_plans, paper_quantity


def candidate(symbol='AAA', headline='Routine company update'):
    return {
        'symbol': symbol,
        'sector': 'Information Technology',
        'quantitative': {
            'price': 100.0, 'atr_14': 2.0, 'atr_pct': 2.0,
            'technical_score': 10.0, 'return_5d': 4.0, 'return_20d': 8.0,
            'relative_strength_spy': 5.0, 'relative_strength_qqq': 4.0,
            'momentum_score': 5.0, 'volume_ratio': 1.1, 'rsi_14': 55.0,
            'sma_20': 95.0, 'sma_50': 90.0, 'sma_200': 80.0,
            'macd_histogram': 1.0, 'high_20': 105.0,
            'max_abs_daily_return_20d_pct': 5.0,
        },
        'recent_news': [{'headline': headline, 'summary': ''}],
    }


def buy(symbol='AAA', qty=8, tier='medium', target=110.0):
    return {
        'symbol': symbol, 'decision': 'BUY', 'strength': 'medium',
        'setup_type': 'TREND_CONTINUATION', 'thesis': 'Fixture.',
        'bull_case': 'Continuation.', 'bear_case': 'Failure.', 'risks': [],
        'invalidation': 'Support fails.', 'entry_rationale': 'Near support.',
        'entry_price': 100.0, 'stop_price': 95.0, 'target_price': target,
        'expected_holding_days': 7, 'time_stop_days': 7,
        'exit_rule': 'Exit on close below SMA20.', 'risk_tier': tier,
        'suggested_quantity': qty, 'evidence_ids': [], 'missing_information': [],
    }


class QualityTests(unittest.TestCase):
    def test_trend_setup_is_classified(self):
        c = analyze_candidate(candidate())
        self.assertEqual(c['quality_profile']['setup_type'], 'TREND_CONTINUATION')
        self.assertIsNone(exclusion_reason(c, 50))

    def test_pending_acquisition_is_hard_excluded(self):
        c = analyze_candidate(candidate(headline='Buyer to acquire Company in definitive agreement'))
        self.assertIn('M_AND_A_PENDING', c['quality_profile']['hard_event_flags'])
        self.assertIn('Special situation excluded', exclusion_reason(c, 0))

    def test_unclassified_setup_can_be_excluded(self):
        c = candidate(); c['quantitative'].update({'sma_20': 110, 'sma_50': 105, 'sma_200': 120,
                                                  'relative_strength_spy': -4, 'momentum_score': -2})
        c = analyze_candidate(c)
        self.assertEqual(c['quality_profile']['setup_type'], 'UNCLASSIFIED')
        self.assertIn('No supported', exclusion_reason(c, 0))


class SizingTests(unittest.TestCase):
    def policy(self):
        return SizingPolicy(strategy_capital_usd=Decimal('10000'))

    def payload(self, symbols=('AAA',)):
        return {'candidates': [analyze_candidate(candidate(s)) for s in symbols],
                'sizing_policy': self.policy().model_payload()}

    def test_astra_quantity_within_limit_is_kept(self):
        report = {'selected_symbols': ['AAA'], 'evaluations': [buy(qty=8)]}
        plan = build_trade_plans(report, self.payload(), self.policy())[0]
        self.assertTrue(plan['valid']); self.assertEqual(plan['validated_quantity'], 8)
        self.assertFalse(plan['quantity_was_clipped'])

    def test_astra_quantity_is_safety_capped(self):
        report = {'selected_symbols': ['AAA'], 'evaluations': [buy(qty=50)]}
        plan = build_trade_plans(report, self.payload(), self.policy())[0]
        self.assertEqual(plan['safe_max_quantity'], 10)
        self.assertEqual(plan['validated_quantity'], 10)
        self.assertTrue(plan['quantity_was_clipped'])

    def test_paper_notional_cap_clips(self):
        report = {'selected_symbols': ['AAA'], 'evaluations': [buy(qty=10)]}
        plan = build_trade_plans(report, self.payload(), self.policy())[0]
        self.assertEqual(paper_quantity(plan, 750), 7)

    def test_no_capital_means_no_authorized_quantity(self):
        policy = SizingPolicy(strategy_capital_usd=None)
        report = {'selected_symbols': ['AAA'], 'evaluations': [buy(qty=None)]}
        plan = build_trade_plans(report, self.payload(), policy)[0]
        self.assertTrue(plan['valid']); self.assertIsNone(plan['validated_quantity'])

    def test_bad_reward_risk_is_rejected(self):
        report = {'selected_symbols': ['AAA'], 'evaluations': [buy(qty=5, target=106.0)]}
        plan = build_trade_plans(report, self.payload(), self.policy())[0]
        self.assertFalse(plan['valid']); self.assertIn('Reward/risk', plan['validation_error'])

    def test_total_risk_cap_applies_across_three_buys(self):
        symbols = ('AAA', 'BBB', 'CCC')
        report = {'selected_symbols': list(symbols),
                  'evaluations': [buy(s, qty=15, tier='high') for s in symbols]}
        plans = build_trade_plans(report, self.payload(symbols), self.policy())
        self.assertEqual(plans[0]['validated_quantity'], 15)
        self.assertEqual(plans[1]['validated_quantity'], 15)
        self.assertFalse(plans[2]['valid'])
        self.assertIn('do not permit one whole share', plans[2]['validation_error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
