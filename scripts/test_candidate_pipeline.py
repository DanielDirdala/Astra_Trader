"""Build and inspect sector candidate packages; never call OpenAI or submit orders."""
import json
from collections import Counter

from src.weekly_selector import WeeklySelector


def main() -> int:
    candidates = WeeklySelector().build_candidates()
    if not candidates:
        print("No research candidates were produced.")
        return 1
    print(f"\nSECTOR CANDIDATE TEST | {len(candidates)} candidates")
    counts = Counter(row["candidate_data"]["sector"] for row in candidates)
    for sector, count in sorted(counts.items()):
        print(f"  {sector}: {count}")
    for row in candidates:
        payload = row["candidate_data"]
        print(f"{row['symbol']:<8} {payload['sector']:<28} "
              f"score={row['quantitative_score']:8.2f} "
              f"news={len(payload.get('recent_news', [])):2}")
    print("\nFIRST FULL RESEARCH PACKAGE")
    print(json.dumps(candidates[0]["candidate_data"], indent=2, default=str, allow_nan=False))
    print("\nNo OpenAI calls or trading orders were made by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
