"""DB support isolated from the existing Database class; no execution methods."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.astra_review import PROMPT_VERSION, WeeklyReview, response_text, usage_estimate


class ReviewStore:
    def __init__(self, connect=None):
        self._connect_override = connect

    def connect(self):
        if self._connect_override is not None:
            return self._connect_override()
        import psycopg
        from psycopg.rows import dict_row
        from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
        # Keyword arguments safely handle punctuation/spaces in passwords.
        return psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                               user=DB_USER, password=DB_PASSWORD,
                               row_factory=dict_row, connect_timeout=10,
                               application_name="astra_research_review")

    def initialize(self, path: Path):
        with self.connect() as conn, conn.cursor() as cur:
            # Fail clearly before changes if prerequisite tables/columns do not match.
            cur.execute("SELECT id, event_type, metadata FROM public.system_events LIMIT 0")
            cur.execute("""SELECT id, symbol, action, entry_price, stop_price, target_price,
                           suggested_quantity, confidence, expected_holding_days, thesis,
                           bull_case, bear_case, invalidation_reason, model_name,
                           prompt_version, raw_response, status
                           FROM public.astra_decisions LIMIT 0""")
            cur.execute(path.read_text(encoding="utf-8"))
            self._check_tables(cur)

    @staticmethod
    def _check_tables(cur):
        cur.execute("""SELECT id, source_event_id, selection_id, request_fingerprint,
                       attempt, model_requested, prompt_version, request_spec,
                       input_payload, status, started_at, finished_at, response_id,
                       output_text, final_report, decision_ids, error_message
                       FROM public.astra_review_runs LIMIT 0""")
        cur.execute("""SELECT review_id, recorded_at, response_id, model_returned,
                       service_tier, input_tokens, cached_input_tokens, output_tokens,
                       reasoning_tokens, cost_low_usd, cost_high_usd, rates, raw_usage
                       FROM public.astra_api_usage LIMIT 0""")

    def check_tables(self):
        with self.connect() as conn, conn.cursor() as cur:
            self._check_tables(cur)

    def load_selection(self, selection_id=None):
        sql = """SELECT id, event_timestamp, metadata FROM public.system_events
                 WHERE event_type = 'SECTOR_CANDIDATES_CREATED'"""
        params = []
        if selection_id is not None:
            sql += " AND metadata->>'selection_id' = %s"
            params.append(str(selection_id))
        sql += " ORDER BY event_timestamp DESC, id DESC LIMIT 1"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        if not row:
            raise RuntimeError("No completed sector selection found. Run scripts.test_candidate_pipeline first.")
        return row

    def claim(self, event_id, payload, spec, fingerprint, attempt):
        from psycopg.types.json import Jsonb
        review_id = uuid4()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO public.astra_review_runs
                (id, source_event_id, selection_id, request_fingerprint, attempt,
                 model_requested, prompt_version, request_spec, input_payload, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'STARTED')
                ON CONFLICT (request_fingerprint) DO NOTHING
                RETURNING id, status;""",
                (review_id, event_id, payload["selection_id"], fingerprint, attempt,
                 spec["model"], PROMPT_VERSION, Jsonb(spec), Jsonb(payload)))
            inserted = cur.fetchone()
            if inserted:
                return inserted, True
            cur.execute("SELECT id, status FROM public.astra_review_runs WHERE request_fingerprint = %s",
                        (fingerprint,))
            return cur.fetchone(), False

    def capture_response(self, review_id, response):
        """Commit usage BEFORE parsing so incomplete/invalid outputs are accounted for."""
        from psycopg.types.json import Jsonb
        usage = usage_estimate(response)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE public.astra_review_runs SET response_id=%s, output_text=%s
                           WHERE id=%s AND status='STARTED' RETURNING id""",
                        (response.get("id"), response_text(response), review_id))
            if cur.fetchone() is None:
                raise RuntimeError("Review is no longer STARTED; refusing to replace stored response.")
            cur.execute("""INSERT INTO public.astra_api_usage
                (review_id, response_id, model_returned, service_tier, input_tokens,
                 cached_input_tokens, output_tokens, reasoning_tokens, cost_low_usd,
                 cost_high_usd, rates, raw_usage)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (review_id) DO NOTHING""",
                (review_id, usage["response_id"], usage["model_returned"], usage["service_tier"],
                 usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"],
                 usage["reasoning_tokens"], usage["cost_low_usd"], usage["cost_high_usd"],
                 Jsonb(usage["rates"]) if usage["rates"] is not None else None,
                 Jsonb(usage["raw_usage"]) if usage["raw_usage"] is not None else None))
        return usage

    def complete(self, review_id, report: WeeklyReview):
        from psycopg.types.json import Jsonb
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT status, response_id, model_requested, input_payload
                           FROM public.astra_review_runs WHERE id=%s FOR UPDATE""", (review_id,))
            run = cur.fetchone()
            if run is None or run["status"] != "STARTED" or not run["response_id"]:
                raise RuntimeError("Review is not ready to complete.")
            decision_ids = []
            for item in report.evaluations:
                if item.decision == "PASS":
                    continue  # Kept in the full report, not mislabelled as HOLD.
                raw = {"review_id": str(review_id), "research_only": True,
                       "execution_eligible": False, "selection_id": run["input_payload"]["selection_id"],
                       "application_warnings": run["input_payload"]["application_warnings"],
                       "evaluation": item.model_dump(mode="json"),
                       "note": "No account sizing; strength is not a win probability."}
                cur.execute("""INSERT INTO public.astra_decisions
                    (symbol, action, entry_price, stop_price, target_price,
                     suggested_quantity, confidence, expected_holding_days,
                     thesis, bull_case, bear_case, invalidation_reason,
                     model_name, prompt_version, raw_response, status)
                    VALUES (%s,%s,%s,%s,%s,NULL,NULL,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')
                    RETURNING id""",
                    (item.symbol, item.decision, item.entry_price, item.stop_price, item.target_price,
                     item.expected_holding_days, item.thesis, item.bull_case, item.bear_case,
                     item.invalidation, run["model_requested"], PROMPT_VERSION, Jsonb(raw)))
                decision_ids.append(cur.fetchone()["id"])
            cur.execute("""UPDATE public.astra_review_runs SET status='COMPLETED',
                           finished_at=NOW(), final_report=%s, decision_ids=%s WHERE id=%s""",
                        (Jsonb(report.model_dump(mode="json")), Jsonb(decision_ids), review_id))
            cur.execute("""INSERT INTO public.system_events(event_type,message,metadata)
                           VALUES ('ASTRA_REVIEW_COMPLETED',%s,%s)""",
                        (f"Research review complete: {len(report.evaluations)} candidates; no orders.",
                         Jsonb({"review_id": str(review_id), "selected_symbols": report.selected_symbols,
                                "decision_ids": decision_ids, "execution_eligible": False})))
        return decision_ids

    def fail(self, review_id, status, message):
        if status not in {"INCOMPLETE", "REFUSED", "INVALID", "API_ERROR", "UNKNOWN", "SAVE_ERROR"}:
            raise ValueError("Invalid failure status.")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE public.astra_review_runs SET status=%s,
                           finished_at=NOW(), error_message=%s
                           WHERE id=%s AND status='STARTED'""", (status, message[:2000], review_id))

    def get_review(self, review_id=None):
        with self.connect() as conn, conn.cursor() as cur:
            if review_id:
                cur.execute("SELECT * FROM public.astra_review_runs WHERE id=%s", (review_id,))
            else:
                cur.execute("SELECT * FROM public.astra_review_runs ORDER BY started_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None, None
            cur.execute("SELECT * FROM public.astra_api_usage WHERE review_id=%s", (row["id"],))
            usage = cur.fetchone()
        return row, usage

    def weekly_costs(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) AS runs,
                COUNT(*) FILTER (WHERE u.cost_low_usd IS NULL) AS unknown_cost_runs,
                SUM(u.cost_low_usd) AS cost_low_usd, SUM(u.cost_high_usd) AS cost_high_usd
                FROM public.astra_review_runs r
                LEFT JOIN public.astra_api_usage u ON u.review_id=r.id
                WHERE r.started_at >=
                    (date_trunc('week', NOW() AT TIME ZONE 'America/New_York')
                     AT TIME ZONE 'America/New_York')""")
            return cur.fetchone()
