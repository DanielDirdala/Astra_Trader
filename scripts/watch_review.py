"""Monitor saved Astra WATCH zones against a fresh Alpaca snapshot.

No OpenAI generation and no brokerage order is created by this command.
"""
from __future__ import annotations

import argparse
from uuid import UUID


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=UUID, help="Completed review UUID; default latest completed review")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    from src.us_market_ops import ROOT, AlpacaHTTP, Settings, quote_context, utcnow
    from src.astra_review_store import ReviewStore
    from src.watch_zones import watch_state

    load_dotenv(ROOT / ".env")
    store = ReviewStore()
    row, _ = store.get_review(args.review)
    if not row:
        raise ValueError("Review not found.")
    if row.get("status") != "COMPLETED" or not row.get("final_report"):
        raise ValueError(f"Review status is {row.get('status')}; a completed report is required.")

    watches = [e for e in row["final_report"].get("evaluations", []) if e.get("decision") == "WATCH"]
    if not watches:
        print("No WATCH evaluations in this review.")
        return 0

    symbols = sorted({e["symbol"] for e in watches})
    settings = Settings.load()
    api = AlpacaHTTP()
    try:
        raw = api.get(
            "/v2/stocks/snapshots",
            {"symbols": ",".join(symbols), "feed": settings.feed},
        )
        clock = api.get("/v2/clock", trading=True)
        received = utcnow()
    finally:
        api.close()

    print(f"WATCH MONITOR | review {row['id']}")
    print(f"Feed: {settings.feed} | regular market open: {bool(clock.get('is_open'))}")
    print("No OpenAI call or order was made.\n")

    triggered = 0
    for ev in watches:
        symbol = ev["symbol"]
        live = quote_context(raw.get(symbol, {}), received, settings.quote_max_age, bool(clock.get("is_open")))
        status = watch_state(ev, live)
        print(f"{symbol}: {status['state']}")
        print(
            f"  bid={status['bid']} ask={status['ask']} midpoint={status['midpoint']} "
            f"fresh={status['quote_fresh']} age={status['quote_age_seconds']}s"
        )
        if status["watch_buy_zone_low"] is not None:
            print(f"  buy zone: {status['watch_buy_zone_low']} - {status['watch_buy_zone_high']}")
        if status["watch_breakout_trigger"] is not None:
            print(f"  breakout price trigger: >= {status['watch_breakout_trigger']}")
        condition = ev.get("watch_trigger_condition")
        if condition:
            print(f"  Astra condition: {condition}")
        print(f"  expires after sessions: {ev.get('watch_expires_after_sessions')}")
        if status["state"] in {"BUY_ZONE_PRICE_TRIGGER", "BREAKOUT_PRICE_TRIGGER"}:
            triggered += 1
            print("  ACTION: refresh/capture and re-review; this is NOT an order signal.")
        print()

    print(f"Price-triggered WATCH names: {triggered}/{len(watches)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
