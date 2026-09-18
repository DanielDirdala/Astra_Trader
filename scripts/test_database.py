from src.database import Database


def main():

    db = Database()

    info = (
        db.test_connection()
    )

    print()
    print(
        "ASTRA DATABASE TEST"
    )
    print(
        "-------------------"
    )

    print(
        f"Database: "
        f"{info['database_name']}"
    )

    print(
        f"User:     "
        f"{info['database_user']}"
    )

    print(
        f"Time:     "
        f"{info['server_time']}"
    )

    with db.connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM information_schema.tables
                WHERE table_schema = 'public';
                """
            )

            count = (
                cur.fetchone()[
                    "count"
                ]
            )

    print()
    print(
        f"Public tables: {count}"
    )

    print()
    print(
        "PostgreSQL connection "
        "successful."
    )


if __name__ == "__main__":
    main()