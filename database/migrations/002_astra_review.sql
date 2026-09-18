-- Additive research tables only. No existing price/candidate/order data is changed.
CREATE TABLE IF NOT EXISTS public.astra_review_runs (
    id UUID PRIMARY KEY,
    source_event_id BIGINT NOT NULL REFERENCES public.system_events(id),
    selection_id UUID NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    model_requested VARCHAR(100) NOT NULL,
    prompt_version VARCHAR(50) NOT NULL,
    request_spec JSONB NOT NULL,
    input_payload JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('STARTED','COMPLETED','INCOMPLETE','REFUSED','INVALID','API_ERROR','UNKNOWN','SAVE_ERROR')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    response_id TEXT UNIQUE,
    output_text TEXT,
    final_report JSONB,
    decision_ids JSONB,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS public.astra_api_usage (
    id BIGSERIAL PRIMARY KEY,
    review_id UUID NOT NULL UNIQUE REFERENCES public.astra_review_runs(id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_id TEXT,
    model_returned TEXT,
    service_tier TEXT,
    input_tokens BIGINT,
    cached_input_tokens BIGINT,
    output_tokens BIGINT,
    reasoning_tokens BIGINT,
    cost_low_usd NUMERIC(20,8),
    cost_high_usd NUMERIC(20,8),
    rates JSONB,
    raw_usage JSONB
);
CREATE INDEX IF NOT EXISTS idx_astra_review_started
    ON public.astra_review_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_astra_usage_recorded
    ON public.astra_api_usage(recorded_at DESC);
