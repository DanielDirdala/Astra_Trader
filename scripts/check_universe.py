"""Report desired coverage, loaded history, and latest scan coverage by sector."""
from collections import Counter

from src.universe import load_universe, sector_counts


def main() -> int:
    from src.database import Database
    universe = load_universe()
    db = Database()
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, COUNT(*) AS bars, MAX(bar_timestamp) AS latest_bar
                FROM public.market_snapshots
                WHERE timeframe = '1Day'
                GROUP BY symbol;
            """)
            histories = {row["symbol"]: row for row in cur.fetchall()}
    scan_id = db.get_latest_scan_id()
    scanned = set()
    if scan_id is not None:
        scanned = {row["symbol"] for row in db.get_scan_results(scan_id=scan_id, limit=None)}
    loaded, warmed, accepted = Counter(), Counter(), Counter()
    for stock in universe["stocks"]:
        symbol, sector = stock["symbol"], stock["sector"]
        if symbol in histories:
            loaded[sector] += 1
            warmed[sector] += int(histories[symbol]["bars"] >= 200)
        accepted[sector] += int(symbol in scanned)
    print(f"\n{universe['fund']} membership as of {universe['holdings_as_of']}")
    print(f"{'Sector':<28} {'Universe':>8} {'Loaded':>8} {'200+ bars':>10} {'In scan':>8}")
    print("-" * 68)
    for sector, count in sector_counts(universe).items():
        print(f"{sector:<28} {count:>8} {loaded[sector]:>8} {warmed[sector]:>10} {accepted[sector]:>8}")
    print(f"\nLatest identified scan: {scan_id}")
    print("Loaded is not a freshness/quality guarantee. In scan reflects the existing scanner's filters.")
    for benchmark in ("SPY", "QQQ"):
        row = histories.get(benchmark)
        print(f"{benchmark} latest stored bar: {row['latest_bar'] if row else 'MISSING'}")
    missing = [stock["symbol"] for stock in universe["stocks"] if stock["symbol"] not in histories]
    print(f"Stocks with no stored daily history: {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
