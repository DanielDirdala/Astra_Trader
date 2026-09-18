from pathlib import Path

import psycopg

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / 'database' / 'migrations' / '001_weekly_pipeline.sql'
SCHEMA_PATH = ROOT / 'database' / 'schema.sql'


# EXPLAIN, without ANALYZE, plans these statements without inserting rows.
UPSERT_CHECKS = (
    """
    EXPLAIN INSERT INTO public.market_snapshots
        (symbol, bar_timestamp, timeframe)
    VALUES ('__SCHEMA_TEST__', CURRENT_TIMESTAMP, '1Day')
    ON CONFLICT (symbol, bar_timestamp, timeframe) DO NOTHING;
    """,
    """
    EXPLAIN INSERT INTO public.news_events (symbol, alpaca_news_id)
    VALUES ('__SCHEMA_TEST__', -1)
    ON CONFLICT (symbol, alpaca_news_id) DO NOTHING;
    """,
    """
    EXPLAIN INSERT INTO public.weekly_candidates (week_start, symbol)
    VALUES (CURRENT_DATE, '__SCHEMA_TEST__')
    ON CONFLICT (week_start, symbol) DO NOTHING;
    """,
)


def snapshot_count(cursor) -> int | None:
    cursor.execute("SELECT to_regclass('public.market_snapshots');")
    if cursor.fetchone()[0] is None:
        return None
    cursor.execute('SELECT COUNT(*) FROM public.market_snapshots;')
    return int(cursor.fetchone()[0])


def verify_upgrade(cursor) -> None:
    required = (
        ('market_snapshots', 'bar_timestamp', 'timestamp with time zone'),
        ('scan_results', 'scan_id', 'uuid'),
        ('news_events', 'alpaca_news_id', 'bigint'),
    )
    for table, column, expected_type in required:
        cursor.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s AND column_name = %s;
            """,
            (table, column),
        )
        row = cursor.fetchone()
        if row is None or row[0] != expected_type:
            raise RuntimeError(
                f'{table}.{column} must exist with type {expected_type}.'
            )

    for statement in UPSERT_CHECKS:
        cursor.execute(statement)
        cursor.fetchall()


def main() -> int:
    print('\nASTRA DATABASE INITIALIZATION')
    print('-----------------------------')
    try:
        migration_sql = MIGRATION_PATH.read_text(encoding='utf-8')
        schema_sql = SCHEMA_PATH.read_text(encoding='utf-8')

        with psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SET LOCAL search_path TO public;')
                cursor.execute("SET LOCAL lock_timeout = '10s';")
                cursor.execute("SET LOCAL statement_timeout = '120s';")

                before = snapshot_count(cursor)
                print(f'Existing market snapshots: {before if before is not None else 0}')

                print('Applying compatibility migration...')
                cursor.execute(migration_sql)

                print('Applying current schema.sql...')
                cursor.execute(schema_sql)

                print('Checking column types and ON CONFLICT targets...')
                verify_upgrade(cursor)

                after = snapshot_count(cursor)
                if before is not None and after != before:
                    raise RuntimeError(
                        'Market snapshot count changed. Migration cancelled; '
                        'stop data loaders before retrying.'
                    )

                cursor.execute(
                    'SELECT COUNT(*) FROM public.scan_results WHERE scan_id IS NULL;'
                )
                legacy_count = cursor.fetchone()[0]

        # The connection context commits only after all operations succeed.
        print('Database initialization and v0.1 compatibility checks passed.')
        print(f'Market snapshots after migration: {after}')
        if legacy_count:
            print(
                f'Preserved {legacy_count} legacy scan rows without a run ID. '
                'Run a fresh scanner before fetching news or selecting candidates.'
            )
        return 0

    except (OSError, RuntimeError, psycopg.Error) as error:
        print('\nINITIALIZATION FAILED: no changes from this transaction were committed.')
        print(error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
