"""Offline tests: mocked API/DB, no keys, network, billing, or order submissions."""
from __future__ import annotations

import copy
import inspect
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.astra_review import (
    AstraReviewer, WeeklyReview, build_review_input, request_fingerprint,
    request_spec, response_has_refusal, response_text, usage_estimate, validate_review,
)
from src.astra_review_store import ReviewStore
from scripts.run_astra_review import main, process_response

NOW = datetime.now(timezone.utc)
SID = "e9a1db58-8213-4fdf-8ed8-551b19103c23"
SCAN = "c3928f80-9648-42fb-8159-af83a5bb55ab"


def metadata():
    return {"selection_id": SID, "scan_id": SCAN,
            "week_start": (NOW.date() - timedelta(days=NOW.weekday())).isoformat(),
            "built_at": NOW.isoformat(), "candidates": [
                {"symbol": symbol, "sector": sector, "industry": None,
                 "selection_id": SID, "scan_id": SCAN,
                 "quantitative": {"price": 100.0, "technical_score": 1.0},
                 "market_context": {"market_regime": "mixed"},
                 "recent_news": [{"headline": "Example supplied news", "summary": "Research fixture",
                                  "url": "https://example.com/news", "published_at": NOW.isoformat()}]}
                for symbol, sector in [("AAA", "Health Care"), ("BBB", "Information Technology")]]}


def report_data():
    return {"market_summary": "Insufficient verified freshness for current trading.",
            "coverage_limitations": ["Partial shortlist only."], "selected_symbols": ["AAA"],
            "additional_research": [], "evaluations": [
                {"symbol": "AAA", "decision": "BUY", "strength": "medium", "setup_type": "TREND_CONTINUATION",
                 "thesis": "Hypothetical setup.", "bull_case": "Continuation.", "bear_case": "Failure.",
                 "risks": ["Gap risk."], "invalidation": "Support fails.", "entry_rationale": "Enter near support.",
                 "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
                 "expected_holding_days": 10, "time_stop_days": 10, "exit_rule": "Exit on daily close below SMA20.",
                 "risk_tier": "medium", "suggested_quantity": None, "evidence_ids": ["NEWS:AAA:1"],
                 "missing_information": ["Portfolio context and live quotes."]},
                {"symbol": "BBB", "decision": "PASS", "strength": "low", "setup_type": "NONE",
                 "thesis": "No setup.", "bull_case": "", "bear_case": "", "risks": [], "invalidation": "",
                 "entry_rationale": "", "entry_price": None, "stop_price": None, "target_price": None,
                 "expected_holding_days": None, "time_stop_days": None, "exit_rule": "",
                 "risk_tier": None, "suggested_quantity": None, "evidence_ids": [], "missing_information": []}]}


def response_data(status="completed"):
    return {"id": "resp_test", "model": "gpt-6-astra", "service_tier": "default", "status": status,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(report_data())}]}],
            "usage": {"input_tokens": 20000, "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens": 4000, "output_tokens_details": {"reasoning_tokens": 1000}}}


def fake_connection(fetch_results):
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchone.side_effect = fetch_results
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = cur
    return conn, cur


def fake_json_modules():
    # Used only inside mocked-storage tests when Psycopg is not installed here.
    parent = types.ModuleType("psycopg")
    types_mod = types.ModuleType("psycopg.types")
    json_mod = types.ModuleType("psycopg.types.json")
    json_mod.Jsonb = lambda value: value
    return {"psycopg": parent, "psycopg.types": types_mod, "psycopg.types.json": json_mod}


class InputTests(unittest.TestCase):
    def test_completed_sector_event_contract(self):
        result = build_review_input(metadata(), now=NOW)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["selection_id"], SID)
        self.assertTrue(result["research_only"])

    def test_source_input_not_mutated(self):
        source = metadata()
        build_review_input(source, now=NOW)
        self.assertNotIn("source_id", source["candidates"][0]["recent_news"][0])

    def test_sources_assigned(self):
        result = build_review_input(metadata(), now=NOW)
        self.assertEqual(result["candidates"][0]["recent_news"][0]["source_id"], "NEWS:AAA:1")

    def test_duplicate_candidate_fails(self):
        data = metadata(); data["candidates"].append(copy.deepcopy(data["candidates"][0]))
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_empty_candidates_fails(self):
        data = metadata(); data["candidates"] = []
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_mixed_selection_fails(self):
        data = metadata(); data["candidates"][0]["scan_id"] = SID
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_stale_selection_requires_explicit_historical(self):
        data = metadata(); data["built_at"] = (NOW - timedelta(days=8)).isoformat()
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)
        result = build_review_input(data, now=NOW, historical=True)
        self.assertTrue(result["historical_review"])

    def test_future_selection_fails(self):
        data = metadata(); data["built_at"] = (NOW + timedelta(hours=1)).isoformat()
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_naive_datetime_fails(self):
        data = metadata(); data["built_at"] = NOW.replace(tzinfo=None).isoformat()
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_nan_fails(self):
        data = metadata(); data["candidates"][0]["quantitative"]["rsi"] = float("nan")
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_missing_price_fails(self):
        data = metadata(); data["candidates"][0]["quantitative"]["price"] = None
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)

    def test_boolean_price_fails(self):
        data = metadata(); data["candidates"][0]["quantitative"]["price"] = True
        with self.assertRaises(ValueError): build_review_input(data, now=NOW)


class SchemaTests(unittest.TestCase):
    def setUp(self): self.payload = build_review_input(metadata(), now=NOW)

    def assert_invalid(self, data):
        with self.assertRaises(ValueError): validate_review(json.dumps(data), self.payload)

    def test_valid_report(self):
        self.assertEqual(validate_review(json.dumps(report_data()), self.payload).selected_symbols, ["AAA"])

    def test_no_trades_valid(self):
        data = report_data(); data["selected_symbols"] = []
        item = data["evaluations"][0]; item["decision"] = "WATCH"
        for k in ["entry_price", "stop_price", "target_price", "expected_holding_days", "time_stop_days", "risk_tier", "suggested_quantity"]:
            item[k] = None
        item["setup_type"] = "NONE"; item["entry_rationale"] = ""; item["exit_rule"] = ""
        self.assertEqual(validate_review(json.dumps(data), self.payload).selected_symbols, [])

    def test_unknown_stock_fails(self):
        data = report_data(); data["evaluations"][1]["symbol"] = "CCC"; self.assert_invalid(data)

    def test_omitted_stock_fails(self):
        data = report_data(); data["evaluations"].pop(); self.assert_invalid(data)

    def test_duplicate_stock_fails(self):
        data = report_data(); data["evaluations"].append(data["evaluations"][0]); self.assert_invalid(data)

    def test_invented_news_id_fails(self):
        data = report_data(); data["evaluations"][0]["evidence_ids"] = ["NEWS:AAA:88"]; self.assert_invalid(data)

    def test_other_stock_news_id_fails(self):
        data = report_data(); data["evaluations"][0]["evidence_ids"] = ["NEWS:BBB:1"]; self.assert_invalid(data)

    def test_mismatched_selected_list_fails(self):
        data = report_data(); data["selected_symbols"] = []; self.assert_invalid(data)

    def test_self_approval_field_rejected(self):
        data = report_data(); data["evaluations"][0]["status"] = "APPROVED"; self.assert_invalid(data)

    def test_negative_price_fails(self):
        data = report_data(); data["evaluations"][0]["entry_price"] = -1; self.assert_invalid(data)

    def test_bad_long_stop_fails(self):
        data = report_data(); data["evaluations"][0]["stop_price"] = 105; self.assert_invalid(data)

    def test_bad_long_target_fails(self):
        data = report_data(); data["evaluations"][0]["target_price"] = 95; self.assert_invalid(data)

    def test_watch_prices_fails(self):
        data = report_data(); data["evaluations"][1]["entry_price"] = 12; self.assert_invalid(data)

    def test_boolean_holding_days_fails(self):
        data = report_data(); data["evaluations"][0]["expected_holding_days"] = True; self.assert_invalid(data)

    def test_empty_thesis_fails(self):
        data = report_data(); data["evaluations"][0]["thesis"] = " "; self.assert_invalid(data)

    def test_buy_requires_complete_stop(self):
        data = report_data(); data["evaluations"][0]["stop_price"] = None
        self.assert_invalid(data)

    def test_json_schema_has_no_optional_properties(self):
        def walk(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertFalse(value["additionalProperties"])
                    self.assertEqual(set(value["required"]), set(value["properties"]))
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(WeeklyReview.model_json_schema())


class UsageTests(unittest.TestCase):
    def test_range(self):
        result = usage_estimate(response_data())
        self.assertEqual(result["cost_low_usd"], Decimal("0.4"))
        self.assertEqual(result["cost_high_usd"], Decimal("0.45"))

    def test_reasoning_not_double_charged(self):
        data = response_data(); data["usage"]["output_tokens_details"]["reasoning_tokens"] = 3500
        self.assertEqual(usage_estimate(data)["cost_low_usd"], Decimal("0.4"))

    def test_cached_input(self):
        data = response_data(); data["usage"]["input_tokens_details"]["cached_tokens"] = 10000
        self.assertEqual(usage_estimate(data)["cost_low_usd"], Decimal("0.31"))

    def test_unknown_usage_not_zero(self):
        data = response_data(); data.pop("usage")
        self.assertIsNone(usage_estimate(data)["cost_low_usd"])

    def test_unknown_model_not_priced(self):
        data = response_data(); data["model"] = "different-model"
        self.assertIsNone(usage_estimate(data)["cost_low_usd"])

    def test_unknown_tier_not_priced(self):
        data = response_data(); data["service_tier"] = "fast"
        self.assertIsNone(usage_estimate(data)["cost_low_usd"])

    def test_long_context_rate(self):
        data = response_data(); data["usage"]["input_tokens"] = 300000
        result = usage_estimate(data)
        self.assertEqual(result["cost_low_usd"], Decimal("6.3"))

    def test_invalid_usage_not_priced(self):
        data = response_data(); data["usage"]["input_tokens_details"]["cached_tokens"] = 50000
        self.assertIsNone(usage_estimate(data)["cost_low_usd"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_review_input(metadata(), now=NOW)

    def test_no_tools_sent(self):
        spec = request_spec(self.payload)
        self.assertNotIn("tools", spec)
        self.assertEqual(spec["service_tier"], "default")
        self.assertFalse(spec["store"])
        self.assertTrue(spec["text"]["format"]["strict"])

    def test_one_mocked_request(self):
        client = MagicMock(); client.responses.create.return_value.model_dump.return_value = response_data()
        reviewer = AstraReviewer(client=client)
        result = reviewer.request_once(request_spec(self.payload))
        self.assertEqual(result["id"], "resp_test")
        client.responses.create.assert_called_once()

    def test_stable_fingerprint(self):
        spec = request_spec(self.payload)
        self.assertEqual(request_fingerprint(spec), request_fingerprint(copy.deepcopy(spec)))
        self.assertNotEqual(request_fingerprint(spec, 1), request_fingerprint(spec, 2))

    def test_complete_records_usage_before_proposals(self):
        store = MagicMock(); store.capture_response.return_value = {}; store.complete.return_value = [88]
        result = process_response(store, SID, response_data(), self.payload)
        self.assertEqual(result[0], "COMPLETED")
        self.assertEqual([call[0] for call in store.method_calls], ["capture_response", "complete"])

    def test_incomplete_records_usage_no_proposals(self):
        store = MagicMock(); data = response_data("incomplete")
        data["incomplete_details"] = {"reason": "max_output_tokens"}
        result = process_response(store, SID, data, self.payload)
        self.assertEqual(result[0], "INCOMPLETE")
        store.capture_response.assert_called_once(); store.complete.assert_not_called()

    def test_invalid_report_records_usage_no_proposals(self):
        store = MagicMock(); data = response_data(); data["output"][0]["content"][0]["text"] = "not json"
        result = process_response(store, SID, data, self.payload)
        self.assertEqual(result[0], "INVALID"); store.complete.assert_not_called()

    def test_refusal_records_usage_no_proposals(self):
        store = MagicMock(); data = response_data()
        data["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot answer."}]
        self.assertTrue(response_has_refusal(data))
        result = process_response(store, SID, data, self.payload)
        self.assertEqual(result[0], "REFUSED"); store.complete.assert_not_called()

    def test_response_text_ignores_reasoning(self):
        data = response_data(); data["output"].insert(0, {"type": "reasoning", "summary": []})
        self.assertEqual(response_text(data), json.dumps(report_data()))

    def test_dry_run_never_calls_api_or_writes_db(self):
        with patch("scripts.run_astra_review.ReviewStore") as cls, \
             patch("scripts.run_astra_review.AstraReviewer") as agent, \
             patch("scripts.run_astra_review.write_json"), \
             patch("builtins.print"), \
             patch.object(sys, "argv", ["run_astra_review"]), \
             patch.dict(os.environ, {"ASTRA_MODEL": "gpt-6-astra"}):
            store = cls.return_value; store.load_selection.return_value = {"id": 10, "metadata": metadata()}
            self.assertEqual(main(), 0)
            agent.assert_not_called(); store.claim.assert_not_called(); store.complete.assert_not_called()

    def test_pending_insert_only(self):
        report = validate_review(json.dumps(report_data()), self.payload)
        conn, cur = fake_connection([
            {"status": "STARTED", "response_id": "resp_test", "model_requested": "gpt-6-astra",
             "input_payload": self.payload}, {"id": 88}])
        store = ReviewStore(connect=lambda: conn)
        with patch.dict(sys.modules, fake_json_modules()):
            self.assertEqual(store.complete(SID, report), [88])
        inserts = [c.args for c in cur.execute.call_args_list if "INSERT INTO public.astra_decisions" in c.args[0]]
        self.assertEqual(len(inserts), 1)
        self.assertIn("'PENDING'", inserts[0][0])
        self.assertIn("NULL,NULL", inserts[0][0])
        self.assertFalse(inserts[0][1][-1]["execution_eligible"])
        self.assertTrue(inserts[0][1][-1]["research_only"])

    def test_duplicate_claim_does_not_insert_again(self):
        conn, cur = fake_connection([None, {"id": SID, "status": "COMPLETED"}])
        with patch.dict(sys.modules, fake_json_modules()):
            row, created = ReviewStore(connect=lambda: conn).claim(
                1, self.payload, request_spec(self.payload), "a" * 64, 1)
        self.assertFalse(created); self.assertEqual(row["status"], "COMPLETED")
        self.assertIn("ON CONFLICT (request_fingerprint) DO NOTHING", cur.execute.call_args_list[0].args[0])

    def test_source_uses_frozen_event_not_mutable_candidate_rows(self):
        conn, cur = fake_connection([{"id": 1, "metadata": metadata()}])
        event = ReviewStore(connect=lambda: conn).load_selection()
        self.assertEqual(event["metadata"]["selection_id"], SID)
        sql = cur.execute.call_args.args[0]
        self.assertIn("SECTOR_CANDIDATES_CREATED", sql)
        self.assertNotIn("FROM weekly_candidates", sql)

    def test_no_broker_dependencies(self):
        import src.astra_review as adapter
        import src.astra_review_store as store
        self.assertNotIn("from src.broker", inspect.getsource(adapter))
        self.assertNotIn("from src.broker", inspect.getsource(store))
        self.assertNotIn("submit_order(", inspect.getsource(adapter))


if __name__ == "__main__":
    unittest.main(verbosity=2)
