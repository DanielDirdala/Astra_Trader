"""Refresh sector membership with public holdings and read-only Alpaca checks."""
import argparse

from src.universe import UNIVERSE_PATH, refresh_universe, sector_counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fund", choices=["IVV", "ITOT"], default="IVV")
    args = parser.parse_args()
    try:
        data = refresh_universe(args.fund)
    except Exception as error:
        print(f"UNIVERSE REFRESH FAILED: {type(error).__name__}: {error}")
        print("No orders were submitted. The previous active universe, if present, was not replaced.")
        return 1
    print(f"\nUNIVERSE: {data['fund']} | holdings as of {data['holdings_as_of']}")
    print(f"Source equities: {data['source_equities']}")
    print(f"Alpaca-validated stocks: {len(data['stocks'])}")
    print(f"Excluded/unmatched source entries: {len(data['excluded'])}")
    for sector, count in sector_counts(data).items():
        print(f"  {sector:<28} {count:>5}")
    print(f"Benchmarks (not stock candidates): {', '.join(data['benchmarks'])}")
    print(f"Cache: {UNIVERSE_PATH}")
    print("Excluded entries and source provenance are recorded in the cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
