-- Additive, separate operational data. No existing tables are dropped or truncated.
CREATE TABLE IF NOT EXISTS public.astra_daily_cache (
    symbol varchar(20) NOT NULL,
    feed varchar(16) NOT NULL,
    adjustment varchar(16) NOT NULL,
    session_date date NOT NULL,
    bar_timestamp timestamptz NOT NULL,
    bar jsonb NOT NULL,
    provenance text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(symbol,feed,adjustment,session_date)
);
CREATE TABLE IF NOT EXISTS public.astra_sync_state (
    symbol varchar(20) NOT NULL,
    feed varchar(16) NOT NULL,
    adjustment varchar(16) NOT NULL,
    last_full_fetch timestamptz,
    first_managed_sync timestamptz NOT NULL DEFAULT now(),
    last_sync timestamptz NOT NULL DEFAULT now(),
    row_count integer NOT NULL,
    newest_session date,
    PRIMARY KEY(symbol,feed,adjustment)
);
CREATE TABLE IF NOT EXISTS public.astra_market_contexts (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS public.astra_paper_tickets (
    id uuid PRIMARY KEY,
    review_id uuid NOT NULL,
    symbol varchar(20) NOT NULL,
    account_id text NOT NULL,
    client_order_id varchar(48) NOT NULL UNIQUE,
    state text NOT NULL CHECK(state IN ('PREPARED','SUBMITTING','SUBMITTED','UNKNOWN','REJECTED')),
    order_payload jsonb NOT NULL,
    order_sha256 text NOT NULL,
    prepared_at timestamptz NOT NULL DEFAULT now(),
    submit_before timestamptz NOT NULL,
    approved_at timestamptz,
    acknowledged_earnings_unknown boolean NOT NULL DEFAULT false,
    broker_order jsonb,
    last_checked_at timestamptz,
    error text,
    UNIQUE(review_id,symbol)
);
