"""Show the last COMPLETE sector selection for a week, not leftover older rows."""
import argparse
from datetime import date
from collections import Counter

from src.weekly_selector import monday_for_date


def main() -> int:
    from src.database import Database
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=date.fromisoformat, help="Week-start date, YYYY-MM-DD")
    args = parser.parse_args()
    week = monday_for_date(args.week)
    with Database().connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT metadata FROM system_events
                   WHERE event_type = 'SECTOR_CANDIDATES_CREATED'
                     AND metadata->>'week_start' = %s
                   ORDER BY event_timestamp DESC, id DESC LIMIT 1;""",
                (week.isoformat(),),
            )
            row = cur.fetchone()
    if row is None:
        print("No completed sector selection for this week. Run scripts.test_candidate_pipeline.")
        return 0
    metadata = row["metadata"]
    candidates = metadata["candidates"]
    print(f"\nWeek: {week} | selection {metadata['selection_id']}")
    print(f"Scan: {metadata['scan_id']} | generated {metadata['built_at']}")
    for sector, count in sorted(Counter(item["sector"] for item in candidates).items()):
        print(f"  {sector}: {count}")
    print()
    for item in candidates:
        quant = item["quantitative"]
        print(f"{item['symbol']:<8} {item['sector']:<28} "
              f"score={float(quant['technical_score']):8.2f} "
              f"news={len(item.get('recent_news', [])):2}")
    print("\nThese are research candidates, not approved orders or guarantees of performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
