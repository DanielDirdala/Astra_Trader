"""Offline long-only FIFO research reporting tests, not broker accounting validation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock
import unittest
from src.pnl_tracker import PnLTracker, period_start, decimal_number
NOW = datetime(2026,9,18,15,30,tzinfo=timezone.utc)
CREATED = "2026-08-01T00:00:00Z"

def fill(identifier,symbol,side,qty,price,when):
    return {"id":identifier,"activity_type":"FILL","type":"fill","symbol":symbol,
            "side":side,"qty":str(qty),"price":str(price),"transaction_time":when}

def fixture():
    return [fill("buy","TESTA","buy",10,100,"2026-09-01T15:00:00Z"),
            fill("sell","TESTA","sell",10,107.5,"2026-09-16T15:00:00Z"),
            {"id":"fee","activity_type":"FEE","date":"2026-09-16","net_amount":"-1"},
            {"id":"deposit","activity_type":"CSD","date":"2026-09-15","net_amount":"5000"}]

class TestPnL(unittest.TestCase):
    def setUp(self):
        self.activities = fixture()
        self.pnl = PnLTracker.calculate(self.activities, [], account_created_at=CREATED, as_of=NOW,
                                       history_complete=True, external_costs_usd=2)

    def calc(self, rows=None, positions=None, **kwargs):
        return PnLTracker.calculate(self.activities if rows is None else rows,
            [] if positions is None else positions, account_created_at=CREATED,
            as_of=NOW, history_complete=True, external_costs_usd=2, **kwargs)

    def test_fifo_carries_opening_basis_before_period(self):
        self.assertEqual(self.pnl["realized_gross_usd"], "75.00")

    def test_fees_and_external_costs(self):
        self.assertEqual(self.pnl["net_realized_after_known_costs_usd"], "72.00")

    def test_deposit_not_profit(self):
        self.assertEqual(self.pnl["net_cash_transfers_usd"], "5000.00")
        self.assertEqual(self.pnl["realized_gross_usd"], "75.00")

    def test_duplicate_activity_counted_once(self):
        self.assertEqual(self.calc(self.activities + [self.activities[0]])["realized_gross_usd"], "75.00")

    def test_conflicting_duplicate_invalid(self):
        changed = {**self.activities[0], "price": "101"}
        self.assertFalse(self.calc(self.activities+[changed])["complete"])

    def test_missing_opening_basis_invalid(self):
        self.assertFalse(self.calc(self.activities[1:])["complete"])

    def test_corporate_action_invalid(self):
        self.assertFalse(self.calc(self.activities+[{"id": "split", "activity_type": "SSP", "date": "2026-09-10"}])["complete"])

    def test_position_mismatch_invalid(self):
        p = {"symbol": "TESTA", "side": "long", "qty": "1", "unrealized_pl": "1"}
        self.assertFalse(self.calc(positions=[p])["complete"])

    def test_partial_fill_fifo(self):
        rows = [fill("b1", "TESTA", "buy", 5, 100, "2026-09-01T14:00:00Z"),
                fill("b2", "TESTA", "buy", 5, 110, "2026-09-01T15:00:00Z"),
                fill("s", "TESTA", "sell", 7, 120, "2026-09-17T15:00:00Z")]
        p = {"symbol": "TESTA", "side": "long", "qty": "3", "unrealized_pl": "30"}
        result = self.calc(rows, [p])
        self.assertTrue(result["complete"])
        self.assertEqual(result["realized_gross_usd"], "120.00")
        self.assertEqual(result["current_unrealized_usd"], "30.00")

    def test_unrealized_does_not_count_as_realized(self):
        rows = self.activities+[fill("hold", "TESTB", "buy", 2, 100, "2026-09-17T15:00:00Z")]
        p = {"symbol": "TESTB", "side": "long", "qty": "2", "unrealized_pl": "18"}
        result = self.calc(rows, [p])
        self.assertEqual(result["net_realized_after_known_costs_usd"], "72.00")
        self.assertEqual(result["current_unrealized_usd"], "18.00")

    def test_missing_external_cost_is_not_zero(self):
        result = PnLTracker.calculate(self.activities, [], account_created_at=CREATED,
            as_of=NOW, history_complete=True)
        self.assertIsNone(result["net_realized_after_known_costs_usd"])

    def test_incomplete_history_never_certified(self):
        result = PnLTracker.calculate(self.activities, [], account_created_at=CREATED, as_of=NOW)
        self.assertFalse(result["complete"])

    def test_period_7_and_14(self):
        self.assertEqual(period_start(NOW, 14).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).day, 5)
        self.assertEqual(period_start(NOW, 7).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).day, 12)

    def test_nonfinite_numbers_rejected(self):
        for value in (None, True, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decimal_number(value)

    def test_repeated_pagination_token_rejected(self):
        api = Mock()
        api.get.return_value = [{"id": str(i)} for i in range(100)]
        with self.assertRaises(ValueError):
            PnLTracker(api).fetch_activities(CREATED, NOW)

    def test_all_activity_pages_fetched(self):
        api = Mock()
        api.get.side_effect = [[{"id": str(i)} for i in range(100)], [{"id": "101"}]]
        self.assertEqual(len(PnLTracker(api).fetch_activities(CREATED, NOW)), 101)

    def test_same_time_fills_flag_ambiguity(self):
        duplicate_time = fill("another", "TESTA", "buy", 1, 100, self.activities[0]["transaction_time"])
        self.assertFalse(self.calc(self.activities+[duplicate_time])["complete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
