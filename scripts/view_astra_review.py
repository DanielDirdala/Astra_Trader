"""View a stored Astra research review and this week's logged token-cost estimate."""
import argparse
from pathlib import Path
from uuid import UUID

from src.astra_review_store import ReviewStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=UUID, help="Review ID; default most recent attempt")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    store = ReviewStore()
    row, usage = store.get_review(args.id)
    if not row:
        print("No Astra review found.")
        return 0
    print(f"\nReview: {row['id']} | {row['status']}")
    print(f"Selection: {row['selection_id']} | Model requested: {row['model_requested']}")
    print(f"Started: {row['started_at']} | Response: {row['response_id']}")
    print("RESEARCH ONLY. Not an approved order or verified current-week buy list.")
    for warning in row["input_payload"]["application_warnings"]:
        print(f"  Warning: {warning}")
    if row["error_message"]:
        print(f"Error: {row['error_message']}")
    report = row["final_report"]
    if report:
        print("\n" + report["market_summary"])
        print("BUY shortlist: " + (", ".join(report["selected_symbols"]) or "NONE"))
        for limitation in report["coverage_limitations"]:
            print(f"  Limitation: {limitation}")
        evidence = {a["source_id"]: a for c in row["input_payload"]["candidates"]
                    for a in c["recent_news"]}
        for item in report["evaluations"]:
            print(f"\n{item['symbol']} | {item['decision']} | assessment: {item['strength']}")
            print(item["thesis"])
            if item["decision"] == "BUY":
                print(f"Setup: {item.get('setup_type')} | risk tier: {item.get('risk_tier')}")
                print(f"Hypothetical entry: {item['entry_price']} | stop: {item['stop_price']} | target: {item['target_price']}")
                print(f"Astra quantity: {item.get('suggested_quantity')} | holding days: {item['expected_holding_days']} | time stop: {item.get('time_stop_days')}")
                if item.get('entry_rationale'): print(f"Entry rationale: {item['entry_rationale']}")
                if item.get('exit_rule'): print(f"Indicator exit rule: {item['exit_rule']}")
                print(f"Bull case: {item['bull_case']}\nBear case: {item['bear_case']}")
                print(f"Invalidation: {item['invalidation']}")
            for risk in item["risks"]:
                print(f"  Risk: {risk}")
            for missing in item["missing_information"]:
                print(f"  Missing: {missing}")
            for source_id in item["evidence_ids"]:
                article = evidence[source_id]
                print(f"  {source_id} | {article.get('published_at')} | {article.get('headline')}")
                print(f"    {article.get('url')}")
        if report["additional_research"]:
            print("\nUnverified follow-up research, NOT additional stock selections:")
            for idea in report["additional_research"]:
                print(f"  {idea}")
    if usage:
        print(f"\nUsage: input={usage['input_tokens']}, cached={usage['cached_input_tokens']}, "
              f"output={usage['output_tokens']}, reasoning subset={usage['reasoning_tokens']}")
        if usage["cost_low_usd"] is not None:
            print(f"This call token estimate: ${usage['cost_low_usd']:.4f} - ${usage['cost_high_usd']:.4f}")
    week = store.weekly_costs()
    print(f"\nCurrent week (New York time): {week['runs']} recorded attempts")
    if week["cost_low_usd"] is not None:
        print(f"Known token estimates: ${week['cost_low_usd']:.4f} - ${week['cost_high_usd']:.4f}")
    print(f"Unknown-cost attempts: {week['unknown_cost_runs']}")
    print("Only calls made by this review runner are counted. Check OpenAI billing for the actual total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
