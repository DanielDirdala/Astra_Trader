-- ============================================================
-- ASTRA TRADER DATABASE
-- ============================================================


-- ============================================================
-- MARKET SNAPSHOTS
-- ============================================================

CREATE TABLE IF NOT EXISTS market_snapshots (

    id BIGSERIAL PRIMARY KEY,

    symbol VARCHAR(20) NOT NULL,

    bar_timestamp TIMESTAMPTZ NOT NULL,

    timeframe VARCHAR(20)
        NOT NULL DEFAULT '1Day',

    open NUMERIC(18,6),
    high NUMERIC(18,6),
    low NUMERIC(18,6),
    close NUMERIC(18,6),

    volume BIGINT,
    trade_count BIGINT,
    vwap NUMERIC(18,6),

    sma_20 NUMERIC(18,6),
    sma_50 NUMERIC(18,6),
    sma_200 NUMERIC(18,6),

    ema_8 NUMERIC(18,6),
    ema_21 NUMERIC(18,6),
    ema_50 NUMERIC(18,6),

    rsi_14 NUMERIC(18,6),
    atr_14 NUMERIC(18,6),

    macd NUMERIC(18,6),
    macd_signal NUMERIC(18,6),
    macd_histogram NUMERIC(18,6),

    avg_volume_20 NUMERIC(24,6),
    volume_ratio NUMERIC(18,6),

    high_20 NUMERIC(18,6),
    low_20 NUMERIC(18,6),

    distance_sma_20_pct NUMERIC(18,6),
    distance_sma_50_pct NUMERIC(18,6),
    distance_sma_200_pct NUMERIC(18,6),

    raw_data JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    UNIQUE (
        symbol,
        bar_timestamp,
        timeframe
    )
);


-- ============================================================
-- SCAN RESULTS
-- ============================================================

CREATE TABLE IF NOT EXISTS scan_results (

    id BIGSERIAL PRIMARY KEY,

    scan_id UUID NOT NULL,

    scan_timestamp TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    symbol VARCHAR(20) NOT NULL,

    price NUMERIC(18,6),

    return_1d NUMERIC(18,6),
    return_5d NUMERIC(18,6),
    return_20d NUMERIC(18,6),

    rsi_14 NUMERIC(18,6),

    atr_pct NUMERIC(18,6),

    volume_ratio NUMERIC(18,6),

    relative_strength_spy NUMERIC(18,6),
    relative_strength_qqq NUMERIC(18,6),

    momentum_score NUMERIC(18,6),
    technical_score NUMERIC(18,6),

    metadata JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


-- ============================================================
-- NEWS
-- ============================================================

CREATE TABLE IF NOT EXISTS news_events (

    id BIGSERIAL PRIMARY KEY,

    symbol VARCHAR(20),

    alpaca_news_id BIGINT,

    published_at TIMESTAMPTZ,

    source VARCHAR(255),

    headline TEXT,

    summary TEXT,

    url TEXT,

    event_type VARCHAR(100),

    raw_data JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    UNIQUE (
        symbol,
        alpaca_news_id
    )
);


-- ============================================================
-- WEEKLY CANDIDATES
-- ============================================================

CREATE TABLE IF NOT EXISTS weekly_candidates (

    id BIGSERIAL PRIMARY KEY,

    week_start DATE NOT NULL,

    symbol VARCHAR(20) NOT NULL,

    quantitative_score NUMERIC(18,6),

    momentum_score NUMERIC(18,6),

    candidate_data JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    UNIQUE (
        week_start,
        symbol
    )
);


-- ============================================================
-- ASTRA WEEKLY REPORT
-- ============================================================

CREATE TABLE IF NOT EXISTS astra_weekly_reports (

    id BIGSERIAL PRIMARY KEY,

    week_start DATE NOT NULL,

    generated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    market_regime VARCHAR(100),

    market_summary TEXT,

    selected_symbols JSONB,

    full_report JSONB,

    model_name VARCHAR(100),

    prompt_version VARCHAR(50)
);


-- ============================================================
-- ASTRA INDIVIDUAL DECISIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS astra_decisions (

    id BIGSERIAL PRIMARY KEY,

    symbol VARCHAR(20) NOT NULL,

    decision_timestamp TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    action VARCHAR(10) NOT NULL,

    entry_price NUMERIC(18,6),

    stop_price NUMERIC(18,6),

    target_price NUMERIC(18,6),

    suggested_quantity NUMERIC(18,6),

    confidence NUMERIC(8,6),

    expected_holding_days INTEGER,

    setup_type VARCHAR(100),

    thesis TEXT,

    bull_case TEXT,

    bear_case TEXT,

    invalidation_reason TEXT,

    market_regime VARCHAR(100),

    model_name VARCHAR(100),

    prompt_version VARCHAR(50),

    raw_response JSONB,

    status VARCHAR(20)
        NOT NULL DEFAULT 'PENDING',

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CHECK (
        action IN (
            'BUY',
            'SELL',
            'HOLD',
            'WATCH'
        )
    ),

    CHECK (
        status IN (
            'PENDING',
            'APPROVED',
            'REJECTED',
            'EXPIRED',
            'EXECUTED'
        )
    )
);


-- ============================================================
-- APPROVALS
-- ============================================================

CREATE TABLE IF NOT EXISTS trade_approvals (

    id BIGSERIAL PRIMARY KEY,

    decision_id BIGINT NOT NULL
        REFERENCES astra_decisions(id)
        ON DELETE CASCADE,

    approved BOOLEAN NOT NULL,

    approved_quantity NUMERIC(18,6),

    notes TEXT,

    approval_timestamp TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    UNIQUE(decision_id)
);


-- ============================================================
-- BROKER ORDERS
-- ============================================================

CREATE TABLE IF NOT EXISTS broker_orders (

    id BIGSERIAL PRIMARY KEY,

    decision_id BIGINT
        REFERENCES astra_decisions(id),

    alpaca_order_id VARCHAR(100),

    symbol VARCHAR(20) NOT NULL,

    side VARCHAR(10) NOT NULL,

    quantity NUMERIC(18,6),

    order_type VARCHAR(30),

    limit_price NUMERIC(18,6),

    stop_price NUMERIC(18,6),

    status VARCHAR(50),

    submitted_at TIMESTAMPTZ,

    filled_at TIMESTAMPTZ,

    filled_quantity NUMERIC(18,6),

    filled_avg_price NUMERIC(18,6),

    raw_order JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


-- ============================================================
-- TRADE OUTCOMES
-- ============================================================

CREATE TABLE IF NOT EXISTS trade_outcomes (

    id BIGSERIAL PRIMARY KEY,

    decision_id BIGINT
        REFERENCES astra_decisions(id),

    symbol VARCHAR(20) NOT NULL,

    entry_price NUMERIC(18,6),
    exit_price NUMERIC(18,6),

    entry_timestamp TIMESTAMPTZ,
    exit_timestamp TIMESTAMPTZ,

    quantity NUMERIC(18,6),

    pnl_dollars NUMERIC(18,6),
    pnl_percent NUMERIC(18,6),

    holding_days NUMERIC(12,4),

    max_favorable_excursion NUMERIC(18,6),
    max_adverse_excursion NUMERIC(18,6),

    return_1d NUMERIC(18,6),
    return_3d NUMERIC(18,6),
    return_5d NUMERIC(18,6),
    return_10d NUMERIC(18,6),
    return_20d NUMERIC(18,6),

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


-- ============================================================
-- SOCIAL DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS social_signals (

    id BIGSERIAL PRIMARY KEY,

    symbol VARCHAR(20) NOT NULL,

    signal_timestamp TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    source VARCHAR(100),

    source_user VARCHAR(255),

    signal VARCHAR(50),

    sentiment NUMERIC(8,6),

    confidence NUMERIC(8,6),

    metadata JSONB,

    raw_data JSONB
);


-- ============================================================
-- MODEL / PROMPT VERSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS strategy_versions (

    id BIGSERIAL PRIMARY KEY,

    version VARCHAR(50)
        UNIQUE NOT NULL,

    model_name VARCHAR(100),

    system_prompt TEXT,

    description TEXT,

    parameters JSONB,

    active BOOLEAN
        NOT NULL DEFAULT FALSE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


-- ============================================================
-- SYSTEM EVENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS system_events (

    id BIGSERIAL PRIMARY KEY,

    event_timestamp TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    event_type VARCHAR(100)
        NOT NULL,

    symbol VARCHAR(20),

    decision_id BIGINT
        REFERENCES astra_decisions(id),

    message TEXT,

    metadata JSONB
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS
idx_market_symbol_time
ON market_snapshots (
    symbol,
    bar_timestamp DESC
);

CREATE INDEX IF NOT EXISTS
idx_scan_id
ON scan_results (
    scan_id
);

CREATE INDEX IF NOT EXISTS
idx_scan_score
ON scan_results (
    technical_score DESC
);

CREATE INDEX IF NOT EXISTS
idx_news_symbol_time
ON news_events (
    symbol,
    published_at DESC
);

CREATE INDEX IF NOT EXISTS
idx_weekly_candidates_week
ON weekly_candidates (
    week_start
);

CREATE INDEX IF NOT EXISTS
idx_astra_status
ON astra_decisions (
    status
);

CREATE INDEX IF NOT EXISTS
idx_system_events_time
ON system_events (
    event_timestamp DESC
);