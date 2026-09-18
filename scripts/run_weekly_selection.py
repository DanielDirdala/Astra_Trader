from src.astra_agent import (
    AstraAgent,
)

from src.weekly_selector import (
    WeeklySelector,
)


def main():

    selector = (
        WeeklySelector()
    )

    candidates = (
        selector
        .build_candidates()
    )

    print()
    print(
        "WEEKLY CANDIDATES"
    )
    print(
        "-----------------"
    )

    for candidate in candidates:

        print(
            f"{candidate['symbol']:<6} "
            f"Quant Score: "
            f"{candidate['quantitative_score']:.2f}"
        )

    astra = AstraAgent()

    result = (
        astra
        .analyze_week(
            candidates
        )
    )

    if (
        result.get("status")
        == "MODEL_NOT_CONNECTED"
    ):

        print()
        print(
            "Astra adapter is not "
            "connected yet."
        )

        print()
        print(
            "The candidate pipeline "
            "completed successfully."
        )


if __name__ == "__main__":
    main()