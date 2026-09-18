-- Compatibility migration for the earlier Astra Trader table definitions.
-- Run in a transaction BEFORE the current database/schema.sql.
-- No tables or stored observations are deleted.

DO $migration$
BEGIN
    IF to_regclass('public.scan_results') IS NOT NULL THEN
        ALTER TABLE public.scan_results
            ADD COLUMN IF NOT EXISTS scan_id UUID;

        -- Never invent historical scan groupings. Preserve unidentified
        -- older rows as NULL, but require an ID on future inserts/updates.
        IF EXISTS (
            SELECT 1 FROM public.scan_results WHERE scan_id IS NULL
        ) THEN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.scan_results'::regclass
                  AND conname = 'scan_results_new_scan_id_required'
            ) THEN
                ALTER TABLE public.scan_results
                    ADD CONSTRAINT scan_results_new_scan_id_required
                    CHECK (scan_id IS NOT NULL) NOT VALID;
            END IF;
        ELSE
            ALTER TABLE public.scan_results
                ALTER COLUMN scan_id SET NOT NULL;
        END IF;
    END IF;

    IF to_regclass('public.news_events') IS NOT NULL THEN
        ALTER TABLE public.news_events
            ADD COLUMN IF NOT EXISTS alpaca_news_id BIGINT;

        IF EXISTS (
            SELECT 1 FROM public.news_events
            WHERE symbol IS NOT NULL AND alpaca_news_id IS NOT NULL
            GROUP BY symbol, alpaca_news_id
            HAVING COUNT(*) > 1
        ) THEN
            RAISE EXCEPTION 'Duplicate news keys prevent the migration.'
                USING HINT = 'Review duplicate (symbol, alpaca_news_id) rows; no automatic deletion is performed.';
        END IF;

        CREATE UNIQUE INDEX IF NOT EXISTS
            news_events_symbol_alpaca_news_id_key
            ON public.news_events (symbol, alpaca_news_id);
    END IF;

    IF to_regclass('public.weekly_candidates') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM public.weekly_candidates
            WHERE week_start IS NOT NULL AND symbol IS NOT NULL
            GROUP BY week_start, symbol
            HAVING COUNT(*) > 1
        ) THEN
            RAISE EXCEPTION 'Duplicate weekly candidates prevent the migration.'
                USING HINT = 'Review duplicate (week_start, symbol) rows; no automatic deletion is performed.';
        END IF;

        CREATE UNIQUE INDEX IF NOT EXISTS
            weekly_candidates_week_start_symbol_key
            ON public.weekly_candidates (week_start, symbol);
    END IF;
END;
$migration$;
