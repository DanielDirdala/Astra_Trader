from src.scanner import Scanner

from config import SCANNER_TOP_N


def main():

    scanner = Scanner()

    scan_id, results = (
        scanner.run()
    )

    print()
    print(
        f"SCAN ID: {scan_id}"
    )

    print()
    print(
        "TOP SCANNER RESULTS"
    )
    print(
        "-------------------"
    )

    for index, result in enumerate(
        results[
            :SCANNER_TOP_N
        ],
        start=1,
    ):

        print(
            f"{index:>2}. "
            f"{result['symbol']:<6} "
            f"Price ${result['price']:>8.2f} "
            f"5D {result['return_5d']:>7.2f}% "
            f"20D {result['return_20d']:>7.2f}% "
            f"Score "
            f"{result['technical_score']:>8.2f}"
        )


if __name__ == "__main__":
    main()