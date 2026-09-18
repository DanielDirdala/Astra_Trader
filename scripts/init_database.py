from pathlib import Path

import psycopg

from config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
)


def main():

    root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    schema_path = (
        root
        / "database"
        / "schema.sql"
    )

    schema_sql = (
        schema_path
        .read_text(
            encoding="utf-8"
        )
    )

    connection_string = (
        f"host={DB_HOST} "
        f"port={DB_PORT} "
        f"dbname={DB_NAME} "
        f"user={DB_USER} "
        f"password={DB_PASSWORD}"
    )

    print()
    print(
        "ASTRA DATABASE INITIALIZATION"
    )
    print(
        "-----------------------------"
    )

    with psycopg.connect(
        connection_string
    ) as conn:

        with conn.cursor() as cur:

            cur.execute(
                schema_sql
            )

        conn.commit()

    print(
        "Database schema initialized "
        "successfully."
    )


if __name__ == "__main__":
    main()