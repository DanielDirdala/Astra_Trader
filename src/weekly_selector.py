"""Build sector-aware research packages. No model requests or brokerage orders.

Existing derived weekly rows are not deleted. A committed selection ID identifies
which rows belong to the current batch, so old survivors do not reappear as picks.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from src.sector_selection import candidates_from_scan


def monday_for_date(value: date | None = None) -> date:
    value = value or date.today()
    return value - timedelta(days=value.weekday())


class WeeklySelector:
    def __init__(self, database=None):
        from src.candidate_builder import CandidateBuilder
        from src.database import Database
        from src.market_context import MarketContext
        self.db = database or Database()
        self.builder = CandidateBuilder(database=self.db)
        self.market_context = MarketContext(database=self.db)

    def build_candidates(self, scan_id=None, limit=None):
        scan_id, rows = candidates_from_scan(self.db, scan_id=scan_id, limit=limit)
        market = self.market_context.build()
        week_start = monday_for_date()
        selection_id = str(uuid4())
        built_at = datetime.now(timezone.utc).isoformat()
        output = []
        for row in rows:
            package = self.builder.build(scan_result=row, market_context=market)
            package.update({
                "sector": row["metadata"]["sector"],
                "industry": row["metadata"].get("industry"),
                "scan_id": str(scan_id),
                "selection_id": selection_id,
                "selection_built_at": built_at,
                "classification": row["metadata"],
            })
            output.append({
                "week_start": week_start,
                "symbol": row["symbol"],
                "quantitative_score": float(row["technical_score"]),
                "momentum_score": float(row["momentum_score"]),
                "candidate_data": package,
            })
        self._save_batch(output, scan_id, selection_id, built_at)
        return output

    def _save_batch(self, candidates, scan_id, selection_id, built_at):
        from psycopg.types.json import Jsonb
        # One transaction: either the complete selection is stored or none of it is.
        # Uses existing tables/columns from the already-applied compatibility migration.
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO weekly_candidates
                        (week_start, symbol, quantitative_score, momentum_score, candidate_data)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (week_start, symbol) DO UPDATE SET
                        quantitative_score = EXCLUDED.quantitative_score,
                        momentum_score = EXCLUDED.momentum_score,
                        candidate_data = EXCLUDED.candidate_data;
                    """,
                    [(row["week_start"], row["symbol"], row["quantitative_score"],
                      row["momentum_score"], Jsonb(row["candidate_data"])) for row in candidates],
                )
                cur.execute(
                    """INSERT INTO system_events (event_type, message, metadata)
                       VALUES (%s, %s, %s);""",
                    ("SECTOR_CANDIDATES_CREATED", f"Built {len(candidates)} sector research packages.",
                     Jsonb({"selection_id": selection_id, "scan_id": str(scan_id),
                            "week_start": candidates[0]["week_start"].isoformat(),
                            "built_at": built_at, "symbols": [row["symbol"] for row in candidates],
                            "candidates": [row["candidate_data"] for row in candidates]})),
                )
