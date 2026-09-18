"""Default: preview saved candidates. --send: make one billable research request.

No broker imports, no order submission, no approvals. The legacy trading scripts
must remain disabled: a research_only JSON field is NOT an access-control boundary.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.astra_review import (
    AstraReviewer, DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_MODEL,
    build_review_input, encode_json, request_fingerprint, request_spec,
    response_has_refusal, response_text, validate_review,
)
from src.astra_review_store import ReviewStore


def write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def safe_fail(store, review_id, status, message):
    try:
        store.fail(review_id, status, message)
    except Exception as error:
        print(f"Could not record failure in PostgreSQL ({type(error).__name__}).")
        print("Keep the local artifacts. Do not repeat a paid request to fix a storage problem.")


def process_response(store, review_id, response, payload):
    """Persist usage before validation; commit proposals+report together only on success."""
    usage = store.capture_response(review_id, response)
    if response.get("status") != "completed":
        status = "INCOMPLETE" if response.get("status") == "incomplete" else "UNKNOWN"
        reason = (response.get("incomplete_details") or {}).get("reason", response.get("status"))
        store.fail(review_id, status, f"Response did not complete: {reason}")
        return status, None, usage, []
    if response_has_refusal(response):
        store.fail(review_id, "REFUSED", "The model returned a refusal. No proposals saved.")
        return "REFUSED", None, usage, []
    try:
        report = validate_review(response_text(response), payload)
    except Exception as error:
        store.fail(review_id, "INVALID", f"Response validation failed: {type(error).__name__}: {error}")
        return "INVALID", None, usage, []
    decisions = store.complete(review_id, report)
    return "COMPLETED", report, usage, decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Authorize one billable API request")
    parser.add_argument("--selection", type=UUID, help="Exact saved selection ID; default latest completed selection")
    parser.add_argument("--historical", action="store_true", help="Allow an old selection for historical research, not current trading")
    parser.add_argument("--max-picks", type=int, default=5)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--attempt", type=int, default=1,
                        help="Change deliberately for a NEW billable attempt; no automatic retries")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    from dotenv import load_dotenv
    load_dotenv(root / ".env")
    model = os.getenv("ASTRA_MODEL", DEFAULT_MODEL).strip()
    store = ReviewStore()
    event = store.load_selection(args.selection)
    payload = build_review_input(event["metadata"], max_picks=args.max_picks, historical=args.historical)
    spec = request_spec(payload, model=model, max_output_tokens=args.max_output_tokens)
    fingerprint = request_fingerprint(spec, args.attempt)
    output_dir = root / "reports" / "astra"
    input_path = output_dir / f"{fingerprint}.input.json"
    write_json(input_path, {"source_event_id": event["id"], "request_fingerprint": fingerprint,
                            "input_payload": payload, "request_spec": spec})
    print("\nASTRA RESEARCH REVIEW - NO ORDER EXECUTION")
    print(f"Selection: {payload['selection_id']}")
    print(f"Scan:      {payload['scan_id']}")
    print(f"Built at:  {payload['selection_built_at']}")
    print(f"Model:     {model}")
    print(f"Candidates: {len(payload['candidates'])}; requested maximum BUY ideas: {args.max_picks}")
    for sector, count in sorted(Counter(item.get("sector", "Unknown") for item in payload["candidates"]).items()):
        print(f"  {sector}: {count}")
    print(f"User-payload characters: {len(encode_json(payload)):,} (not an exact token count)")
    print(f"Output-token cap: {args.max_output_tokens:,}, including reasoning")
    print(f"Preview saved: {input_path}")
    print("\nData limitations:")
    for warning in payload["application_warnings"]:
        print(f"  - {warning}")
    if not args.send:
        print("\nPREVIEW ONLY: no OpenAI request or pending proposal was created.")
        print("To send this exact selection, add --send --selection followed by its ID.")
        return 0
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing from the project .env or environment.")
    # Check SDK before reserving a billable attempt.
    from openai import OpenAI  # noqa: F401
    store.check_tables()
    run, created = store.claim(event["id"], payload, spec, fingerprint, args.attempt)
    if not created:
        print(f"\nNot sending: this identical attempt already exists ({run['status']}).")
        print(f"Review ID: {run['id']}")
        print("View the stored review. Only change --attempt intentionally; it can incur another charge.")
        return 0 if run["status"] == "COMPLETED" else 1
    review_id = run["id"]
    response_path = output_dir / f"{review_id}.response.json"
    print(f"\nReview ID: {review_id}")
    print("Sending ONE billable Responses API request. Web tools and SDK retries are disabled.")
    try:
        response = AstraReviewer(api_key=api_key).request_once(spec)
    except Exception as error:
        status_code = getattr(error, "status_code", None)
        request_id = getattr(error, "request_id", None)
        # Do not print raw exception body, which could contain key fragments or sensitive request content.
        message = f"{type(error).__name__}; HTTP={status_code}; request_id={request_id}"
        status = "API_ERROR" if status_code is not None and status_code < 500 else "UNKNOWN"
        safe_fail(store, review_id, status, message)
        write_json(output_dir / f"{review_id}.error.json", {"review_id": str(review_id),
                   "recorded_at": datetime.now(timezone.utc).isoformat(), "error": message,
                   "usage_known": False})
        print(f"Request failed: {message}")
        print("No proposal was saved. A timeout or transport failure may still have incurred usage.")
        print("Check the API dashboard before deliberately starting another attempt.")
        return 1
    # Save a recovery copy before parsing and DB persistence. Never save API keys.
    try:
        write_json(response_path, {"review_id": str(review_id), "request_fingerprint": fingerprint,
                                   "response": response})
    except Exception as error:
        print(f"Warning: local response backup failed ({type(error).__name__}); attempting PostgreSQL storage.")
    try:
        status, report, usage, decision_ids = process_response(store, review_id, response, payload)
    except Exception as error:
        safe_fail(store, review_id, "SAVE_ERROR", f"Persistence failed: {type(error).__name__}")
        print(f"Storage failed ({type(error).__name__}). Keep the response artifact: {response_path}")
        print("Do not make another paid call merely to fix storage; recover this response instead.")
        return 1
    print(f"\nStatus: {status}")
    print(f"Response artifact: {response_path}")
    if usage["input_tokens"] is not None:
        print(f"Input: {usage['input_tokens']:,}; cached subset: {usage['cached_input_tokens']:,}")
        print(f"Output: {usage['output_tokens']:,}; reasoning subset: {usage['reasoning_tokens']:,}")
    if usage["cost_low_usd"] is not None:
        print(f"Standard token-cost estimate: ${usage['cost_low_usd']:.4f} - ${usage['cost_high_usd']:.4f}")
        print("Estimate range allows cache-write uncertainty; not your final invoice or a spending cap.")
    else:
        print("Cost estimate unavailable; usage is unknown or the model/tier needs an updated rate table.")
    if report is None:
        print("No pending proposals were written. The API request can still be billable.")
        return 1
    print("\n" + report.market_summary)
    print("Hypothetical BUY shortlist: " + (", ".join(report.selected_symbols) or "NONE"))
    print(f"Pending research rows (BUY/WATCH): {decision_ids}")
    print("No quantities, approvals, or orders were created. All output is research-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
