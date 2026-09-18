"""Offline regression tests. No credentials, network calls, or DB writes."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from src import universe as u
from src.sector_selection import candidates_from_scan, select_sector_candidates
from src.weekly_selector import WeeklySelector, monday_for_date


CSV = '''Example fund\nFund Holdings as of,"Sep 16, 2026"\nInception Date,"May 15, 2000"\nTicker,Name,Sector,Asset Class,Weight (%)\nAAA,"Example, Inc.",Information Technology,Equity,3.5\nBBB,Example Medical,Health Care,Equity,2.0\nCCC,Example Media,Communication,Equity,1.0\nBRK B,Example Class B,Financials,Equity,1.0\nUSD,US DOLLAR,Cash and/or Derivatives,Cash,0.1\nXTSLA,Money Fund,Cash and/or Derivatives,Money Market,0.1\nFUT,Index Future,Cash and/or Derivatives,Futures,0.1\nLegal disclaimer\n'''


def asset(symbol, **extra):
    return {"symbol": symbol, "status": "active", "asset_class": "us_equity", "tradable": True, **extra}


def fixture():
    sectors = ["Information Technology", "Health Care", "Energy"]
    stocks, rows = [], []
    for s_index, sector in enumerate(sectors):
        for n in range(6):
            symbol = f"X{s_index}{n}"
            stocks.append({"symbol": symbol, "sector": sector, "industry": None})
            rows.append({"symbol": symbol, "technical_score": Decimal(100 - 30 * s_index - n),
                         "momentum_score": Decimal(3), "metadata": {"atr": 1.5},
                         "scan_timestamp": datetime.now(timezone.utc)})
    payload = {"schema_version": 1, "fund": "IVV", "universe_id": "test-universe",
               "holdings_as_of": date.today().isoformat(), "stocks": stocks, "benchmarks": ["SPY", "QQQ"]}
    return payload, rows


class ParserTests(unittest.TestCase):
    def test_preamble_quotes_sectors_and_cash_exclusion(self):
        as_of, rows = u.parse_holdings("\ufeff" + CSV, minimum_equities=4)
        self.assertEqual(as_of, "2026-09-16")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["name"], "Example, Inc.")
        self.assertEqual(next(row for row in rows if row["source_symbol"] == "CCC")["sector"], "Communication Services")
        self.assertTrue(all(row["industry"] is None for row in rows))

    def test_wrong_document_rejected(self):
        with self.assertRaises(ValueError):
            u.parse_holdings("<html>Access denied</html>", minimum_equities=1)

    def test_small_response_rejected(self):
        with self.assertRaises(ValueError):
            u.parse_holdings(CSV, minimum_equities=300)

    def test_duplicate_equity_rejected(self):
        with self.assertRaises(ValueError):
            u.parse_holdings(CSV + "AAA,Another,Information Technology,Equity,1\n", minimum_equities=1)

    def test_unknown_equity_sector_rejected(self):
        with self.assertRaises(ValueError):
            u.parse_holdings(CSV.replace("Health Care", "Unmapped"), minimum_equities=1)

    def test_broker_mapping_and_inactive_exclusion(self):
        _, rows = u.parse_holdings(CSV, minimum_equities=1)
        stocks, excluded, benchmarks = u.match_assets(
            rows, [asset("AAA"), asset("BBB", tradable=False), asset("CCC", status="inactive"),
                   asset("BRK.B"), asset("SPY"), asset("QQQ")])
        self.assertEqual([row["symbol"] for row in stocks], ["AAA", "BRK.B"])
        self.assertEqual(len(excluded), 2)
        self.assertEqual(benchmarks, ["SPY", "QQQ"])

    def test_ambiguous_mapping_not_guessed(self):
        stocks, excluded, _ = u.match_assets(
            [{"source_symbol": "BRK B", "sector": "Financials"}],
            [asset("BRK.B"), asset("BRK-B"), asset("SPY"), asset("QQQ")])
        self.assertEqual(stocks, [])
        self.assertIn("Ambiguous", excluded[0]["reason"])

    def test_benchmarks_required(self):
        with self.assertRaises(ValueError):
            u.match_assets([], [asset("SPY")])

    def test_atomic_write_and_cache_read(self):
        payload, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "universe.json"
            u._write_json_atomic(path, payload)
            with patch.object(u, "UNIVERSE_PATH", path):
                self.assertEqual(len(u.get_stock_universe()), 18)
                self.assertEqual(len(u.get_universe()), 20)
                self.assertEqual(u.get_sector("X00"), "Information Technology")
                self.assertIsNone(u.get_sector("SPY"))
            self.assertEqual(json.loads(path.read_text())["universe_id"], "test-universe")
        u._read_cached.cache_clear()


class SelectionTests(unittest.TestCase):
    def test_three_per_sector_plus_extra(self):
        payload, rows = fixture()
        original = copy.deepcopy(rows)
        picked = select_sector_candidates(rows, per_sector=3, extra_global=2, universe=payload)
        self.assertEqual(len(picked), 11)
        for sector in ("Information Technology", "Health Care", "Energy"):
            self.assertGreaterEqual(sum(row["metadata"]["sector"] == sector for row in picked), 3)
        self.assertEqual(rows, original)  # Do not mutate DB response objects.

    def test_partial_sector_keeps_available_members(self):
        payload, rows = fixture()
        rows = [row for row in rows if row['symbol'] not in [f'X2{n}' for n in range(1, 6)]]
        picked = select_sector_candidates(rows, per_sector=3, extra_global=0, universe=payload)
        self.assertEqual(len(picked), 7)

    def test_limit_does_not_silently_remove_sectors(self):
        payload, rows = fixture()
        with self.assertRaises(ValueError):
            select_sector_candidates(rows, limit=5, universe=payload)

    def test_no_benchmark_selection(self):
        payload, rows = fixture()
        rows.append({"symbol": "SPY", "technical_score": 9999})
        self.assertNotIn("SPY", {row['symbol'] for row in select_sector_candidates(rows, universe=payload)})

    def test_nan_rejected(self):
        payload, rows = fixture()
        rows[0]["technical_score"] = float("nan")
        with self.assertRaises(ValueError):
            select_sector_candidates(rows, universe=payload)

    def test_duplicate_scan_rows_rejected(self):
        payload, rows = fixture()
        with self.assertRaises(ValueError):
            select_sector_candidates(rows + [rows[0]], universe=payload)

    def test_latest_scan_fetches_all_rows(self):
        payload, rows = fixture()
        class DB:
            def get_latest_scan_id(self):
                return "scan-1"
            def get_scan_results(self, scan_id, limit):
                assert scan_id == "scan-1" and limit is None
                return rows
        with patch("src.sector_selection.load_universe", return_value=payload):
            scan_id, selected = candidates_from_scan(DB())
        self.assertEqual(scan_id, "scan-1")
        self.assertGreater(len(selected), 10)

    def test_stale_scan_stops_candidate_selection(self):
        _, rows = fixture()
        for row in rows:
            row["scan_timestamp"] -= timedelta(days=10)
        class DB:
            def get_latest_scan_id(self):
                return "old"
            def get_scan_results(self, **kwargs):
                return rows
        with self.assertRaises(RuntimeError):
            candidates_from_scan(DB())

    def test_week_date(self):
        self.assertEqual(monday_for_date(date(2026, 9, 17)), date(2026, 9, 14))


class BatchContractTests(unittest.TestCase):
    def test_batch_and_event_share_one_connection(self):
        calls = []
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def executemany(self, sql, params): calls.append(("rows", sql, params))
            def execute(self, sql, params): calls.append(("event", sql, params))
        class Connection:
            def __enter__(self): calls.append(("enter",)); return self
            def __exit__(self, *args): calls.append(("exit",)); return False
            def cursor(self): return Cursor()
        class DB:
            def connect(self): return Connection()
        class Jsonb:
            def __init__(self, obj): self.obj = obj
        stub = types.ModuleType("psycopg.types.json")
        stub.Jsonb = Jsonb
        selector = WeeklySelector.__new__(WeeklySelector)
        selector.db = DB()
        rows = [{"week_start": date(2026, 9, 14), "symbol": "AAA", "quantitative_score": 10.0,
                 "momentum_score": 2.0, "candidate_data": {"symbol": "AAA", "selection_id": "s1"}}]
        with patch.dict(sys.modules, {"psycopg.types.json": stub}):
            selector._save_batch(rows, "scan", "s1", "2026-09-17T00:00:00+00:00")
        self.assertEqual([call[0] for call in calls], ["enter", "rows", "event", "exit"])
        self.assertEqual(calls[1][2][0][1], "AAA")
        self.assertEqual(calls[2][2][0], "SECTOR_CANDIDATES_CREATED")
        self.assertEqual(calls[2][2][2].obj["symbols"], ["AAA"])
        self.assertNotIn("DELETE", calls[1][1].upper())


if __name__ == "__main__":
    unittest.main(verbosity=2)
