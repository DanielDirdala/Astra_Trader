"""Create two additive research tables. Never resets existing market data."""
from pathlib import Path


def main() -> int:
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    from src.astra_review_store import ReviewStore
    path = root / "database" / "migrations" / "002_astra_review.sql"
    ReviewStore().initialize(path)
    print("Astra review tables initialized and required columns checked.")
    print("Existing market data, sector selections and order tables were not rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
