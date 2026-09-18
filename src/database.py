from datetime import timedelta

import psycopg

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
)


class Database:

    def __init__(self):

        self.connection_string = (
            f"host={DB_HOST} "
            f"port={DB_PORT} "
            f"dbname={DB_NAME} "
            f"user={DB_USER} "
            f"password={DB_PASSWORD}"
        )

    # ========================================================
    # CONNECTION
    # ========================================================

    def connect(self):

        return psycopg.connect(
            self.connection_string,
            row_factory=dict_row,
        )

    def test_connection(self):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        current_database()
                            AS database_name,

                        current_user
                            AS database_user,

                        NOW()
                            AS server_time;
                    """
                )

                return cur.fetchone()

    # ========================================================
    # EVENTS
    # ========================================================

    def log_event(
        self,
        event_type,
        message="",
        symbol=None,
        decision_id=None,
        metadata=None,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO system_events (
                        event_type,
                        symbol,
                        decision_id,
                        message,
                        metadata
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )

                    RETURNING id;
                    """,
                    (
                        event_type,
                        symbol,
                        decision_id,
                        message,
                        (
                            Jsonb(metadata)
                            if metadata
                            else None
                        ),
                    )
                )

                return cur.fetchone()["id"]

    # ========================================================
    # MARKET DATA
    # ========================================================

    def save_market_snapshot(
        self,
        symbol,
        timestamp,
        timeframe,
        data,
    ):

        sql = """
        INSERT INTO market_snapshots (

            symbol,
            bar_timestamp,
            timeframe,

            open,
            high,
            low,
            close,

            volume,
            trade_count,
            vwap,

            sma_20,
            sma_50,
            sma_200,

            ema_8,
            ema_21,
            ema_50,

            rsi_14,
            atr_14,

            macd,
            macd_signal,
            macd_histogram,

            avg_volume_20,
            volume_ratio,

            high_20,
            low_20,

            distance_sma_20_pct,
            distance_sma_50_pct,
            distance_sma_200_pct,

            raw_data
        )

        VALUES (

            %(symbol)s,
            %(timestamp)s,
            %(timeframe)s,

            %(open)s,
            %(high)s,
            %(low)s,
            %(close)s,

            %(volume)s,
            %(trade_count)s,
            %(vwap)s,

            %(sma_20)s,
            %(sma_50)s,
            %(sma_200)s,

            %(ema_8)s,
            %(ema_21)s,
            %(ema_50)s,

            %(rsi_14)s,
            %(atr_14)s,

            %(macd)s,
            %(macd_signal)s,
            %(macd_histogram)s,

            %(avg_volume_20)s,
            %(volume_ratio)s,

            %(high_20)s,
            %(low_20)s,

            %(distance_sma_20_pct)s,
            %(distance_sma_50_pct)s,
            %(distance_sma_200_pct)s,

            %(raw_data)s
        )

        ON CONFLICT (
            symbol,
            bar_timestamp,
            timeframe
        )

        DO UPDATE SET

            open =
                EXCLUDED.open,

            high =
                EXCLUDED.high,

            low =
                EXCLUDED.low,

            close =
                EXCLUDED.close,

            volume =
                EXCLUDED.volume,

            trade_count =
                EXCLUDED.trade_count,

            vwap =
                EXCLUDED.vwap,

            sma_20 =
                EXCLUDED.sma_20,

            sma_50 =
                EXCLUDED.sma_50,

            sma_200 =
                EXCLUDED.sma_200,

            ema_8 =
                EXCLUDED.ema_8,

            ema_21 =
                EXCLUDED.ema_21,

            ema_50 =
                EXCLUDED.ema_50,

            rsi_14 =
                EXCLUDED.rsi_14,

            atr_14 =
                EXCLUDED.atr_14,

            macd =
                EXCLUDED.macd,

            macd_signal =
                EXCLUDED.macd_signal,

            macd_histogram =
                EXCLUDED.macd_histogram,

            avg_volume_20 =
                EXCLUDED.avg_volume_20,

            volume_ratio =
                EXCLUDED.volume_ratio,

            high_20 =
                EXCLUDED.high_20,

            low_20 =
                EXCLUDED.low_20,

            distance_sma_20_pct =
                EXCLUDED.distance_sma_20_pct,

            distance_sma_50_pct =
                EXCLUDED.distance_sma_50_pct,

            distance_sma_200_pct =
                EXCLUDED.distance_sma_200_pct,

            raw_data =
                EXCLUDED.raw_data

        RETURNING id;
        """

        params = {
            "symbol":
                symbol.upper(),

            "timestamp":
                timestamp,

            "timeframe":
                timeframe,

            "open":
                data.get("open"),

            "high":
                data.get("high"),

            "low":
                data.get("low"),

            "close":
                data.get("close"),

            "volume":
                data.get("volume"),

            "trade_count":
                data.get(
                    "trade_count"
                ),

            "vwap":
                data.get("vwap"),

            "sma_20":
                data.get("sma_20"),

            "sma_50":
                data.get("sma_50"),

            "sma_200":
                data.get("sma_200"),

            "ema_8":
                data.get("ema_8"),

            "ema_21":
                data.get("ema_21"),

            "ema_50":
                data.get("ema_50"),

            "rsi_14":
                data.get("rsi_14"),

            "atr_14":
                data.get("atr_14"),

            "macd":
                data.get("macd"),

            "macd_signal":
                data.get(
                    "macd_signal"
                ),

            "macd_histogram":
                data.get(
                    "macd_histogram"
                ),

            "avg_volume_20":
                data.get(
                    "avg_volume_20"
                ),

            "volume_ratio":
                data.get(
                    "volume_ratio"
                ),

            "high_20":
                data.get("high_20"),

            "low_20":
                data.get("low_20"),

            "distance_sma_20_pct":
                data.get(
                    "distance_sma_20_pct"
                ),

            "distance_sma_50_pct":
                data.get(
                    "distance_sma_50_pct"
                ),

            "distance_sma_200_pct":
                data.get(
                    "distance_sma_200_pct"
                ),

            "raw_data":
                Jsonb(
                    data.get(
                        "raw_data",
                        {}
                    )
                ),
        }

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    sql,
                    params
                )

                return cur.fetchone()["id"]

    def get_recent_snapshots(
        self,
        symbol,
        limit=250,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM market_snapshots

                    WHERE symbol = %s

                    ORDER BY
                        bar_timestamp DESC

                    LIMIT %s;
                    """,
                    (
                        symbol.upper(),
                        limit,
                    )
                )

                return cur.fetchall()

    def get_loaded_symbols(
        self,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM market_snapshots
                    ORDER BY symbol;
                    """
                )

                return [
                    row["symbol"]
                    for row
                    in cur.fetchall()
                ]

    # ========================================================
    # SCANNER
    # ========================================================

    def save_scan_result(
        self,
        result,
    ):

        sql = """
        INSERT INTO scan_results (

            scan_id,
            symbol,

            price,

            return_1d,
            return_5d,
            return_20d,

            rsi_14,

            atr_pct,
            volume_ratio,

            relative_strength_spy,
            relative_strength_qqq,

            momentum_score,
            technical_score,

            metadata
        )

        VALUES (
            %(scan_id)s,
            %(symbol)s,

            %(price)s,

            %(return_1d)s,
            %(return_5d)s,
            %(return_20d)s,

            %(rsi_14)s,

            %(atr_pct)s,
            %(volume_ratio)s,

            %(relative_strength_spy)s,
            %(relative_strength_qqq)s,

            %(momentum_score)s,
            %(technical_score)s,

            %(metadata)s
        )

        RETURNING id;
        """

        params = dict(
            result
        )

        params["metadata"] = Jsonb(
            result.get(
                "metadata",
                {}
            )
        )

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    sql,
                    params
                )

                return cur.fetchone()["id"]

    def get_scan_results(
        self,
        scan_id,
        limit=None,
    ):

        sql = """
        SELECT *
        FROM scan_results

        WHERE scan_id = %s

        ORDER BY
            technical_score DESC
        """

        params = [
            scan_id
        ]

        if limit:

            sql += " LIMIT %s"

            params.append(
                limit
            )

        sql += ";"

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    sql,
                    params
                )

                return cur.fetchall()

    def get_latest_scan_id(
        self,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT scan_id
                    FROM scan_results
                    ORDER BY
                        scan_timestamp DESC
                    LIMIT 1;
                    """
                )

                row = cur.fetchone()

                if row is None:
                    return None

                return row["scan_id"]

    # ========================================================
    # NEWS
    # ========================================================

    def save_news_event(
        self,
        event,
    ):

        sql = """
        INSERT INTO news_events (

            symbol,
            alpaca_news_id,
            published_at,
            source,
            headline,
            summary,
            url,
            event_type,
            raw_data
        )

        VALUES (
            %(symbol)s,
            %(alpaca_news_id)s,
            %(published_at)s,
            %(source)s,
            %(headline)s,
            %(summary)s,
            %(url)s,
            %(event_type)s,
            %(raw_data)s
        )

        ON CONFLICT (
            symbol,
            alpaca_news_id
        )

        DO NOTHING;
        """

        params = dict(
            event
        )

        params["raw_data"] = Jsonb(
            event.get(
                "raw_data",
                {}
            )
        )

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    sql,
                    params
                )

    def get_recent_news(
        self,
        symbol,
        days=7,
        limit=20,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM news_events

                    WHERE symbol = %s

                    AND published_at >=
                        NOW() - (%s * INTERVAL '1 day')

                    ORDER BY
                        published_at DESC

                    LIMIT %s;
                    """,
                    (
                        symbol.upper(),
                        days,
                        limit,
                    )
                )

                return cur.fetchall()

    # ========================================================
    # WEEKLY CANDIDATES
    # ========================================================

    def save_weekly_candidate(
        self,
        candidate,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO weekly_candidates (

                        week_start,
                        symbol,

                        quantitative_score,
                        momentum_score,

                        candidate_data
                    )

                    VALUES (
                        %(week_start)s,
                        %(symbol)s,

                        %(quantitative_score)s,
                        %(momentum_score)s,

                        %(candidate_data)s
                    )

                    ON CONFLICT (
                        week_start,
                        symbol
                    )

                    DO UPDATE SET

                        quantitative_score =
                            EXCLUDED.quantitative_score,

                        momentum_score =
                            EXCLUDED.momentum_score,

                        candidate_data =
                            EXCLUDED.candidate_data

                    RETURNING id;
                    """,
                    {
                        **candidate,

                        "candidate_data":
                            Jsonb(
                                candidate.get(
                                    "candidate_data",
                                    {}
                                )
                            ),
                    }
                )

                return cur.fetchone()["id"]

    def get_weekly_candidates(
        self,
        week_start,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM weekly_candidates

                    WHERE week_start = %s

                    ORDER BY
                        quantitative_score DESC;
                    """,
                    (
                        week_start,
                    )
                )

                return cur.fetchall()

    # ========================================================
    # ASTRA DECISIONS
    # ========================================================

    def save_astra_decision(
        self,
        decision,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO astra_decisions (

                        symbol,
                        action,

                        entry_price,
                        stop_price,
                        target_price,

                        suggested_quantity,
                        confidence,

                        expected_holding_days,

                        setup_type,

                        thesis,
                        bull_case,
                        bear_case,

                        invalidation_reason,

                        market_regime,

                        model_name,
                        prompt_version,

                        raw_response
                    )

                    VALUES (
                        %(symbol)s,
                        %(action)s,

                        %(entry_price)s,
                        %(stop_price)s,
                        %(target_price)s,

                        %(suggested_quantity)s,
                        %(confidence)s,

                        %(expected_holding_days)s,

                        %(setup_type)s,

                        %(thesis)s,
                        %(bull_case)s,
                        %(bear_case)s,

                        %(invalidation_reason)s,

                        %(market_regime)s,

                        %(model_name)s,
                        %(prompt_version)s,

                        %(raw_response)s
                    )

                    RETURNING id;
                    """,
                    {
                        **decision,

                        "raw_response":
                            Jsonb(
                                decision.get(
                                    "raw_response",
                                    decision
                                )
                            ),
                    }
                )

                return cur.fetchone()["id"]

    def get_pending_decisions(
        self,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM astra_decisions

                    WHERE status = 'PENDING'

                    ORDER BY
                        decision_timestamp DESC;
                    """
                )

                return cur.fetchall()

    def get_decision(
        self,
        decision_id,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM astra_decisions
                    WHERE id = %s;
                    """,
                    (
                        decision_id,
                    )
                )

                return cur.fetchone()

    def approve_trade(
        self,
        decision_id,
        quantity=None,
        notes=None,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO trade_approvals (
                        decision_id,
                        approved,
                        approved_quantity,
                        notes
                    )

                    VALUES (
                        %s,
                        TRUE,
                        %s,
                        %s
                    )

                    ON CONFLICT (
                        decision_id
                    )

                    DO UPDATE SET

                        approved = TRUE,

                        approved_quantity =
                            EXCLUDED.approved_quantity,

                        notes =
                            EXCLUDED.notes,

                        approval_timestamp =
                            NOW();
                    """,
                    (
                        decision_id,
                        quantity,
                        notes,
                    )
                )

                cur.execute(
                    """
                    UPDATE astra_decisions

                    SET status = 'APPROVED'

                    WHERE id = %s;
                    """,
                    (
                        decision_id,
                    )
                )

    def reject_trade(
        self,
        decision_id,
        notes=None,
    ):

        with self.connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO trade_approvals (
                        decision_id,
                        approved,
                        notes
                    )

                    VALUES (
                        %s,
                        FALSE,
                        %s
                    )

                    ON CONFLICT (
                        decision_id
                    )

                    DO UPDATE SET

                        approved = FALSE,

                        notes =
                            EXCLUDED.notes,

                        approval_timestamp =
                            NOW();
                    """,
                    (
                        decision_id,
                        notes,
                    )
                )

                cur.execute(
                    """
                    UPDATE astra_decisions

                    SET status = 'REJECTED'

                    WHERE id = %s;
                    """,
                    (
                        decision_id,
                    )
                )