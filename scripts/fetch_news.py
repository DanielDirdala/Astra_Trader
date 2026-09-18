from src.database import Database
from src.news import NewsService


TOP_SYMBOLS = 20


def main():

    db = Database()

    scan_id = (
        db.get_latest_scan_id()
    )

    if scan_id is None:

        raise RuntimeError(
            "Run scanner first."
        )

    scan_results = (
        db.get_scan_results(
            scan_id,
            TOP_SYMBOLS,
        )
    )

    news = NewsService(
        db
    )

    for result in scan_results:

        symbol = (
            result["symbol"]
        )

        print(
            f"Fetching news: "
            f"{symbol}"
        )

        try:

            articles = (
                news
                .fetch_and_store(
                    symbol,
                    days=7,
                    limit=20,
                )
            )

            print(
                f"  {len(articles)} "
                f"articles stored."
            )

        except Exception as error:

            print(
                f"  ERROR: {error}"
            )


if __name__ == "__main__":
    main()