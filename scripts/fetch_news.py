"""Fetch news for the SAME sector-aware shortlist used by WeeklySelector."""
from collections import Counter

from src.sector_selection import candidates_from_scan


def main() -> int:
    from src.database import Database
    from src.news import NewsService
    db = Database()
    scan_id, rows = candidates_from_scan(db)
    news = NewsService(database=db)
    print(f"\nSECTOR NEWS FETCH | scan {scan_id}")
    print(f"Research candidates: {len(rows)}")
    for sector, count in sorted(Counter(row['metadata']['sector'] for row in rows).items()):
        print(f"  {sector}: {count}")
    successful = failed = processed = 0
    for row in rows:
        symbol = row["symbol"]
        try:
            result = news.fetch_and_store(symbol=symbol, days=7, limit=20)
            # Earlier supplied NewsService versions returned a list; the latest returns an int.
            count = len(result) if isinstance(result, list) else int(result)
            successful += 1
            processed += count
            print(f"{symbol}: {count} articles processed (not necessarily newly inserted)")
        except Exception as error:
            failed += 1
            print(f"{symbol}: NEWS FETCH FAILED: {type(error).__name__}: {error}")
    db.log_event(
        event_type="SECTOR_NEWS_FETCH_FINISHED",
        message=f"{successful} symbols succeeded; {failed} failed.",
        metadata={"scan_id": str(scan_id), "symbols": [row['symbol'] for row in rows],
                  "successful": successful, "failed": failed, "articles_processed": processed},
    )
    print(f"\nSuccessful: {successful}; failed: {failed}; articles processed: {processed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
