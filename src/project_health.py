"""Local diagnostics and additive initialization. No Alpaca or OpenAI calls."""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Verify interfaces rather than just an unreliable table count.
REQUIRED = {
    'market_snapshots': {'symbol': 'varchar', 'bar_timestamp': 'timestamptz'},
    'scan_results': {'scan_id': 'uuid'},
    'news_events': {'alpaca_news_id': 'int8'},
    'weekly_candidates': {'candidate_data': 'jsonb'},
    'system_events': {'metadata': 'jsonb'},
    'astra_decisions': {'raw_response': 'jsonb', 'status': 'varchar'},
    'astra_review_runs': {'id': 'uuid', 'request_fingerprint': 'text', 'input_payload': 'jsonb',
                          'request_spec': 'jsonb', 'status': 'text'},
    'astra_api_usage': {'review_id': 'uuid', 'cost_high_usd': 'numeric', 'output_tokens': 'int8'},
    'astra_daily_cache': {'symbol': 'varchar', 'feed': 'varchar', 'adjustment': 'varchar',
                          'session_date': 'date', 'bar': 'jsonb'},
    'astra_sync_state': {'last_sync': 'timestamptz', 'last_full_fetch': 'timestamptz',
                         'first_managed_sync': 'timestamptz'},
    'astra_market_contexts': {'id': 'uuid', 'payload': 'jsonb'},
    'astra_paper_tickets': {'id': 'uuid', 'order_payload': 'jsonb', 'order_sha256': 'text',
                           'submit_before': 'timestamptz', 'state': 'text'},
}


def connect():
    import psycopg
    from psycopg.rows import dict_row
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    return psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER,
                           password=DB_PASSWORD, connect_timeout=10, row_factory=dict_row,
                           application_name='astra_consolidated_diagnostics')


def check_columns(conn):
    rows = conn.execute("""SELECT table_name,column_name,udt_name
                           FROM information_schema.columns WHERE table_schema='public'""").fetchall()
    actual = {(r['table_name'], r['column_name']): r['udt_name'] for r in rows}
    problems = []
    for table, columns in REQUIRED.items():
        for column, kind in columns.items():
            found = actual.get((table, column))
            if found != kind:
                problems.append(f'{table}.{column}: expected {kind}, found {found or "MISSING"}')
    return problems


def snapshot_counts(conn):
    out = {}
    for table in ('market_snapshots', 'astra_daily_cache'):
        exists = conn.execute('SELECT to_regclass(%s) AS relation', ('public.'+table,)).fetchone()['relation']
        out[table] = conn.execute('SELECT COUNT(*) AS n FROM public.'+table).fetchone()['n'] if exists else 0
    return out


def initialize():
    """All DDL in one transaction. Advisory lock prevents two init jobs racing."""
    with connect() as conn:
        conn.execute("SET LOCAL lock_timeout = '15s'")
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (84392762,))
        before = snapshot_counts(conn)
        paths = [ROOT/'database/migrations/001_weekly_pipeline.sql', ROOT/'database/schema.sql',
                 ROOT/'database/migrations/002_astra_review.sql', ROOT/'database/migrations/003_market_operations.sql']
        for path in paths:
            conn.execute(path.read_text(encoding='utf-8'))
        problems = check_columns(conn)
        if problems:
            raise ValueError('Schema checks failed; transaction rolled back: '+'; '.join(problems))
        after = snapshot_counts(conn)
        if before != after:
            raise ValueError('Snapshot row counts changed unexpectedly; rolling back.')
    print('Schema verified. Existing history preserved:', after)
    print('No account connections, model calls, data adoption, or orders occurred.')
    return 0


def doctor(check_database=False):
    ok = True
    print('ASTRA CONSOLIDATED v0.2 | Python', sys.version.split()[0])
    print('Repository:', ROOT)
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print('WARNING: documented/tested target is Python 3.11-3.13.')
    for package in ('requests','pandas','numpy','psycopg','pydantic','openai','dotenv','alpaca'):
        spec = importlib.util.find_spec(package)
        exists = spec is not None
        print(f'Dependency {package}:', 'found' if exists else 'MISSING')
        ok = ok and exists
    for folder in ('src', 'scripts'):
        for file in (ROOT/folder).glob('*.py'):
            try:
                ast.parse(file.read_text(encoding='utf-8-sig'), filename=str(file))
            except SyntaxError:
                print('Syntax error:', file.relative_to(ROOT)); ok = False
    if importlib.util.find_spec('dotenv'):
        from dotenv import load_dotenv
        import os
        load_dotenv(ROOT/'.env')
        for var in ('ALPACA_API_KEY','ALPACA_SECRET_KEY','DB_NAME','DB_USER','DB_PASSWORD','OPENAI_API_KEY'):
            print(f'{var}:', 'SET (value hidden)' if os.getenv(var) else 'NOT SET')
        from src.research_engine import CostPolicy
        policy = CostPolicy.load()
        print(f'Finalists: {policy.finalists}; max BUY ideas: {policy.max_picks}; max output: {policy.max_output_tokens}')
        print(f'Rolling 7-day model budget: ${policy.rolling_7d_usd}; max attempts: {policy.calls_per_7d}')
        print('Paper submissions enabled:', os.getenv('ASTRA_ENABLE_PAPER_SUBMISSION','false').lower() == 'true')
    universe = ROOT/'data/universe.json'
    if universe.exists():
        data = json.loads(universe.read_text(encoding='utf-8'))
        print('Saved universe entries:',len(data.get('stocks',[])), '(membership alone is not proof of loaded/fresh data)')
    if check_database:
        with connect() as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            problems = check_columns(conn)
            for problem in problems:
                print('SCHEMA:', problem)
            ok = ok and not problems
            print('History row counts:', snapshot_counts(conn))
        print('Database diagnostic was read-only.')
    else:
        print('No database/network checks requested. Add --db for a read-only schema check.')
    print('No model call or brokerage order was made.')
    return 0 if ok else 1
