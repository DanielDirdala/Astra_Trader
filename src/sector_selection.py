"""Coverage-oriented research shortlist, NOT a trade or portfolio-allocation rule."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from src.universe import load_universe

CANDIDATES_PER_SECTOR = 3
EXTRA_GLOBAL_CANDIDATES = 5
MAX_SCAN_AGE_DAYS = 7


def select_sector_candidates(
    rows: list[dict],
    per_sector: int = CANDIDATES_PER_SECTOR,
    extra_global: int = EXTRA_GLOBAL_CANDIDATES,
    limit: int | None = None,
    universe: dict | None = None,
) -> list[dict]:
    if per_sector < 1 or extra_global < 0:
        raise ValueError("per_sector must be positive and extra_global cannot be negative.")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive or None.")
    universe = universe if universe is not None else load_universe()
    metadata = {row["symbol"]: row for row in universe["stocks"]}
    ranked = []
    seen = set()
    for row in rows:
        symbol = row["symbol"]
        if symbol not in metadata:
            continue  # Includes benchmarks and symbols no longer in the universe.
        if symbol in seen:
            raise ValueError(f"Duplicate scanner result for {symbol} in this run.")
        seen.add(symbol)
        try:
            score = float(row["technical_score"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Missing/invalid technical_score for {symbol}") from error
        if not math.isfinite(score):
            raise ValueError(f"Non-finite score for {symbol}")
        sector = metadata[symbol]["sector"]
        enriched = dict(row)
        enriched["metadata"] = {
            **(row.get("metadata") or {}),
            "sector": sector,
            "industry": metadata[symbol].get("industry"),
            "classification_source": f"iShares {universe['fund']} holdings",
            "universe_id": universe["universe_id"],
            "holdings_as_of": universe["holdings_as_of"],
        }
        ranked.append(enriched)
    ranked.sort(key=lambda row: (-float(row["technical_score"]), row["symbol"]))
    groups = defaultdict(list)
    for row in ranked:
        groups[row["metadata"]["sector"]].append(row)
    coverage = {row["symbol"] for group in groups.values() for row in group[:per_sector]}
    if limit is not None and limit < len(coverage):
        raise ValueError(f"limit={limit} would truncate {len(coverage)} sector slots. Use limit=None or a larger value.")
    selected = set(coverage)
    extras = 0
    for row in ranked:
        if extras >= extra_global or (limit is not None and len(selected) >= limit):
            break
        if row["symbol"] not in selected:
            selected.add(row["symbol"])
            extras += 1
    output = []
    for row in ranked:
        if row["symbol"] in selected:
            row["metadata"]["selection_reason"] = (
                "sector_coverage" if row["symbol"] in coverage else "additional_global_candidate"
            )
            output.append(row)
    return output


def candidates_from_scan(database: Any, scan_id: Any = None, limit: int | None = None) -> tuple[Any, list[dict]]:
    scan_id = scan_id if scan_id is not None else database.get_latest_scan_id()
    if scan_id is None:
        raise RuntimeError("No scanner run found. Run python -m scripts.run_scanner first.")
    # Fetch ALL results before grouping. Do not take the global top 10/20 first.
    rows = database.get_scan_results(scan_id=scan_id, limit=None)
    if not rows:
        raise RuntimeError("The selected scanner run has no results.")
    timestamps = []
    for row in rows:
        value = row.get("scan_timestamp")
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeError("Scanner rows must include timezone-aware scan_timestamp values.")
        timestamps.append(value)
    now = datetime.now(timezone.utc)
    if min(timestamps) < now - timedelta(days=MAX_SCAN_AGE_DAYS):
        raise RuntimeError("The scan is more than seven days old. Refresh data and run the scanner again.")
    if max(timestamps) > now + timedelta(minutes=5):
        raise RuntimeError("Scan timestamps are in the future. Check the computer/database clocks.")
    chosen = select_sector_candidates(rows, limit=limit)
    if not chosen:
        raise RuntimeError("No scan results match the refreshed universe. Load its history and re-run the scanner.")
    return scan_id, chosen
