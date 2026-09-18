from datetime import date

from src.database import Database

from src.weekly_selector import (
    monday_for_date,
)


def main():

    db = Database()

    week = monday_for_date(
        date.today()
    )

    rows = (
        db.get_weekly_candidates(
            week
        )
    )

    print()
    print(
        f"Candidates for {week}"
    )
    print(
        "------------------------"
    )

    for row in rows:

        print(
            f"{row['symbol']:<6} "
            f"Score: "
            f"{float(row['quantitative_score']):.2f}"
        )


if __name__ == "__main__":
    main()