"""Dynamic sector-aware US equity universe.

Supports IVV and ITOT holdings as universe sources.

This module:
- downloads holdings
- keeps common equity rows
- skips provider rows classified as "Other"
- safely handles duplicate source tickers
- excludes ambiguous duplicate tickers
- validates symbols against Alpaca active/tradable US equities
- stores the final universe in data/universe.json

It does not place orders.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile

from collections import Counter
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

UNIVERSE_PATH = (
    ROOT
    / "data"
    / "universe.json"
)

ARCHIVE_DIR = (
    ROOT
    / "data"
    / "universe_snapshots"
)


# ============================================================
# BENCHMARKS
# ============================================================

BENCHMARKS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
]


# ============================================================
# CACHE AGE
# ============================================================

MAX_UNIVERSE_AGE_DAYS = 14


# ============================================================
# UNIVERSE SOURCES
# ============================================================

SOURCES = {

    "IVV": {
        "url": (
            "https://www.ishares.com/us/products/"
            "239726/ishares-core-s-p-500-etf/"
            "latest-holdings.csv"
        ),
        "minimum_equities": 300,
    },

    "ITOT": {
        "url": (
            "https://www.ishares.com/us/products/"
            "239724/"
            "ishares-core-s-p-total-u-s-stock-market-etf/"
            "latest-holdings.csv"
        ),
        "minimum_equities": 1000,
    },
}


# ============================================================
# SUPPORTED SECTORS
# ============================================================

SECTORS = {
    "Information Technology",
    "Health Care",
    "Financials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Communication Services",
    "Energy",
    "Utilities",
    "Materials",
    "Real Estate",
}


SECTOR_ALIASES = {
    "Communication":
        "Communication Services",
}


IGNORED_EQUITY_SECTORS = {
    "",
    "Other",
}


# ============================================================
# HOLDINGS PARSER
# ============================================================

def parse_holdings(
    text: str,
    minimum_equities: int = 300,
) -> tuple[str, list[dict]]:
    """
    Parse an iShares holdings CSV.

    Rules:
    - non-equity rows are ignored
    - blank/Other sectors are ignored
    - duplicate ticker + same sector => keep one
    - duplicate ticker + conflicting sector => exclude ticker
    """

    header = None
    holdings_date = None

    records: dict[str, dict] = {}

    ambiguous_tickers: set[str] = set()

    reader = csv.reader(
        io.StringIO(
            text.lstrip("\ufeff")
        )
    )

    for values in reader:

        values = [
            value.strip()
            for value in values
        ]

        if not values:
            pass

        elif not any(values):
            pass

        elif header is None:

            # -----------------------------------------------
            # Holdings date
            # -----------------------------------------------

            if (
                values[0].lower()
                == "fund holdings as of"
                and len(values) > 1
            ):

                for fmt in (
                    "%b %d, %Y",
                    "%B %d, %Y",
                    "%Y-%m-%d",
                ):

                    try:

                        holdings_date = (
                            datetime.strptime(
                                values[1],
                                fmt,
                            ).date()
                        )

                        break

                    except ValueError:
                        pass

            # -----------------------------------------------
            # Detect actual CSV header
            # -----------------------------------------------

            required_columns = {
                "Ticker",
                "Name",
                "Sector",
                "Asset Class",
            }

            if required_columns.issubset(
                set(values)
            ):
                header = values

        else:

            # -----------------------------------------------
            # Only process rows matching header length
            # -----------------------------------------------

            if len(values) == len(header):

                row = dict(
                    zip(
                        header,
                        values,
                    )
                )

                asset_class = (
                    row.get(
                        "Asset Class",
                        ""
                    )
                    .strip()
                    .casefold()
                )

                # -------------------------------------------
                # Stocks/equities only
                # -------------------------------------------

                if asset_class == "equity":

                    ticker = (
                        row.get(
                            "Ticker",
                            ""
                        )
                        .strip()
                        .upper()
                    )

                    valid_ticker = (
                        bool(ticker)
                        and ticker != "-"
                    )

                    if valid_ticker:

                        raw_sector = (
                            row.get(
                                "Sector",
                                ""
                            )
                            .strip()
                        )

                        # -----------------------------------
                        # Ignore provider "Other"
                        # classifications.
                        # -----------------------------------

                        if (
                            raw_sector
                            not in
                            IGNORED_EQUITY_SECTORS
                        ):

                            sector = (
                                SECTOR_ALIASES.get(
                                    raw_sector,
                                    raw_sector,
                                )
                            )

                            if sector not in SECTORS:

                                raise ValueError(
                                    "Unrecognized equity "
                                    "identifier/sector: "
                                    f"{ticker!r}, "
                                    f"{sector!r}"
                                )

                            # -------------------------------
                            # If already known ambiguous,
                            # ignore all later occurrences.
                            # -------------------------------

                            if (
                                ticker
                                not in
                                ambiguous_tickers
                            ):

                                new_record = {
                                    "source_symbol":
                                        ticker,

                                    "name":
                                        row.get(
                                            "Name",
                                            ""
                                        ).strip(),

                                    "sector":
                                        sector,

                                    "industry":
                                        None,
                                }

                                # ---------------------------
                                # First occurrence
                                # ---------------------------

                                if ticker not in records:

                                    records[
                                        ticker
                                    ] = new_record

                                # ---------------------------
                                # Duplicate occurrence
                                # ---------------------------

                                else:

                                    existing = (
                                        records[
                                            ticker
                                        ]
                                    )

                                    existing_sector = (
                                        existing.get(
                                            "sector"
                                        )
                                    )

                                    # -----------------------
                                    # Same ticker but
                                    # conflicting sector:
                                    # exclude completely.
                                    # -----------------------

                                    if (
                                        existing_sector
                                        != sector
                                    ):

                                        records.pop(
                                            ticker,
                                            None,
                                        )

                                        ambiguous_tickers.add(
                                            ticker
                                        )

                                    else:

                                        # -------------------
                                        # Same ticker and
                                        # same sector:
                                        # keep one record.
                                        # -------------------

                                        existing_name = (
                                            existing.get(
                                                "name"
                                            )
                                            or ""
                                        ).strip()

                                        new_name = (
                                            new_record.get(
                                                "name"
                                            )
                                            or ""
                                        ).strip()

                                        if (
                                            not existing_name
                                            and new_name
                                        ):

                                            existing[
                                                "name"
                                            ] = new_name

    # ========================================================
    # VALIDATION
    # ========================================================

    if header is None:

        raise ValueError(
            "Holdings CSV layout could not "
            "be recognized; existing cache "
            "is unchanged."
        )

    if holdings_date is None:

        raise ValueError(
            "Holdings date could not be "
            "recognized; existing cache "
            "is unchanged."
        )

    if len(records) < minimum_equities:

        raise ValueError(
            f"Only {len(records)} eligible "
            f"sector-classified equities parsed; "
            f"expected at least "
            f"{minimum_equities}."
        )

    if ambiguous_tickers:

        print(
            "Skipped ambiguous source tickers: "
            + ", ".join(
                sorted(
                    ambiguous_tickers
                )
            )
        )

    return (
        holdings_date.isoformat(),

        sorted(
            records.values(),
            key=lambda record:
                record[
                    "source_symbol"
                ],
        ),
    )


# ============================================================
# SYMBOL VARIANTS
# ============================================================

def symbol_variants(
    symbol: str,
) -> list[str]:

    original = (
        symbol
        .strip()
        .upper()
    )

    variants = [
        original
    ]

    if re.fullmatch(
        r"[A-Z]+[ .\-/][A-Z]",
        original,
    ):

        parts = re.split(
            r"[ .\-/]",
            original,
        )

        if len(parts) == 2:

            base = parts[0]
            share_class = parts[1]

            variants.extend(
                [
                    f"{base}.{share_class}",
                    f"{base}-{share_class}",
                    f"{base}/{share_class}",
                ]
            )

    return list(
        dict.fromkeys(
            variants
        )
    )


# ============================================================
# ALPACA ASSET MATCHING
# ============================================================

def match_assets(
    records: list[dict],
    assets: Iterable[Any],
) -> tuple[
    list[dict],
    list[dict],
    list[str],
]:

    def field(
        asset: Any,
        key: str,
    ) -> Any:

        if isinstance(
            asset,
            dict,
        ):

            value = asset.get(
                key
            )

        else:

            value = getattr(
                asset,
                key,
                None,
            )

        return getattr(
            value,
            "value",
            value,
        )

    available = {}

    for asset in assets:

        status = field(
            asset,
            "status",
        )

        asset_class = field(
            asset,
            "asset_class",
        )

        tradable = field(
            asset,
            "tradable",
        )

        if (
            status == "active"
            and asset_class == "us_equity"
            and tradable is True
        ):

            symbol_value = field(
                asset,
                "symbol",
            )

            if symbol_value:

                symbol = str(
                    symbol_value
                ).upper()

                available[
                    symbol
                ] = asset

    accepted = []
    excluded = []

    used_symbols = set()

    for record in records:

        source_symbol = (
            record[
                "source_symbol"
            ]
        )

        matches = [
            symbol
            for symbol
            in symbol_variants(
                source_symbol
            )
            if symbol in available
        ]

        if len(matches) == 0:

            excluded.append(
                {
                    **record,

                    "reason":
                        (
                            "No matching active/"
                            "tradable Alpaca "
                            "US equity"
                        ),
                }
            )

        elif len(matches) > 1:

            excluded.append(
                {
                    **record,

                    "reason":
                        (
                            "Ambiguous class-share "
                            "notation"
                        ),

                    "matches":
                        matches,
                }
            )

        else:

            symbol = matches[0]

            if symbol in used_symbols:

                raise ValueError(
                    "Multiple source records "
                    "resolved to Alpaca symbol "
                    f"{symbol}."
                )

            used_symbols.add(
                symbol
            )

            accepted.append(
                {
                    **record,
                    "symbol":
                        symbol,
                }
            )

    benchmarks = [
        symbol
        for symbol
        in BENCHMARKS
        if symbol in available
    ]

    if not {
        "SPY",
        "QQQ",
    }.issubset(
        benchmarks
    ):

        raise ValueError(
            "SPY and QQQ were not verified "
            "as active/tradable benchmarks."
        )

    return (
        sorted(
            accepted,
            key=lambda record:
                record[
                    "symbol"
                ],
        ),

        excluded,

        benchmarks,
    )


# ============================================================
# ATOMIC JSON WRITE
# ============================================================

def _write_json_atomic(
    path: Path,
    payload: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_name = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:

            temp_name = (
                handle.name
            )

            json.dump(
                payload,
                handle,
                indent=2,
                allow_nan=False,
            )

            handle.write(
                "\n"
            )

        os.replace(
            temp_name,
            path,
        )

    finally:

        if temp_name:

            temp_path = Path(
                temp_name
            )

            if temp_path.exists():

                temp_path.unlink()


# ============================================================
# REFRESH UNIVERSE
# ============================================================

def refresh_universe(
    fund: str = "IVV",
) -> dict:

    import requests

    from requests.adapters import (
        HTTPAdapter,
    )

    from urllib3.util.retry import (
        Retry,
    )

    from alpaca.trading.client import (
        TradingClient,
    )

    from alpaca.trading.enums import (
        AssetClass,
        AssetStatus,
    )

    from alpaca.trading.requests import (
        GetAssetsRequest,
    )

    from config import (
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
    )

    fund = (
        fund
        .strip()
        .upper()
    )

    if fund not in SOURCES:

        raise ValueError(
            "fund must be IVV or ITOT"
        )

    if (
        not ALPACA_API_KEY
        or not ALPACA_SECRET_KEY
    ):

        raise ValueError(
            "Alpaca credentials are missing."
        )

    source = SOURCES[
        fund
    ]

    retry = Retry(
        total=3,
        backoff_factor=1,

        status_forcelist=(
            429,
            500,
            502,
            503,
            504,
        ),

        allowed_methods=frozenset(
            {
                "GET",
            }
        ),

        respect_retry_after_header=True,
    )

    with requests.Session() as session:

        session.mount(
            "https://",
            HTTPAdapter(
                max_retries=retry
            ),
        )

        response = session.get(
            source[
                "url"
            ],

            timeout=(
                10,
                60,
            ),
        )

        response.raise_for_status()

        if len(
            response.content
        ) > 15_000_000:

            raise ValueError(
                "Unexpectedly large holdings "
                "response."
            )

        text = response.content.decode(
            "utf-8-sig"
        )

        as_of, records = (
            parse_holdings(
                text,
                source[
                    "minimum_equities"
                ],
            )
        )

    today = datetime.now(
        timezone.utc
    ).date()

    source_date = date.fromisoformat(
        as_of
    )

    age_days = (
        today
        - source_date
    ).days

    if (
        age_days < -1
        or age_days
        > MAX_UNIVERSE_AGE_DAYS
    ):

        raise ValueError(
            f"Holdings source date "
            f"{as_of} is stale or "
            f"in the future."
        )

    client = TradingClient(
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
        paper=True,
    )

    assets = (
        client.get_all_assets(
            GetAssetsRequest(
                status=
                    AssetStatus.ACTIVE,

                asset_class=
                    AssetClass.US_EQUITY,
            )
        )
    )

    (
        stocks,
        excluded,
        benchmarks,
    ) = match_assets(
        records,
        assets,
    )

    minimum = source[
        "minimum_equities"
    ]

    if len(stocks) < minimum:

        raise ValueError(
            f"Only {len(stocks)} eligible "
            f"stocks matched Alpaca; "
            f"minimum is {minimum}."
        )

    surviving_sectors = {
        row[
            "sector"
        ]
        for row
        in stocks
    }

    missing_sectors = (
        SECTORS
        - surviving_sectors
    )

    if missing_sectors:

        raise ValueError(
            "Missing sectors after "
            "Alpaca validation: "
            + ", ".join(
                sorted(
                    missing_sectors
                )
            )
        )

    now = datetime.now(
        timezone.utc
    )

    payload = {

        "schema_version":
            1,

        "universe_id":
            str(
                uuid4()
            ),

        "fund":
            fund,

        "source_url":
            source[
                "url"
            ],

        "holdings_as_of":
            as_of,

        "refreshed_at":
            now.isoformat(),

        "source_equities":
            len(
                records
            ),

        "stocks":
            stocks,

        "benchmarks":
            benchmarks,

        "excluded":
            excluded,
    }

    archive_path = (
        ARCHIVE_DIR
        / (
            f"{now.strftime('%Y%m%dT%H%M%S%fZ')}"
            f"_{fund}.json"
        )
    )

    _write_json_atomic(
        archive_path,
        payload,
    )

    _write_json_atomic(
        UNIVERSE_PATH,
        payload,
    )

    _read_cached.cache_clear()

    return payload


# ============================================================
# CACHE
# ============================================================

@lru_cache(
    maxsize=4
)
def _read_cached(
    path: str,
    modified_ns: int,
) -> dict:

    del modified_ns

    return json.loads(
        Path(
            path
        ).read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# LOAD UNIVERSE
# ============================================================

def load_universe() -> dict:

    if not UNIVERSE_PATH.exists():

        raise RuntimeError(
            "No dynamic universe exists. "
            "Run: "
            "python -m scripts.refresh_universe "
            "--fund ITOT"
        )

    payload = _read_cached(
        str(
            UNIVERSE_PATH
        ),

        UNIVERSE_PATH
        .stat()
        .st_mtime_ns,
    )

    if (
        payload.get(
            "schema_version"
        ) != 1
    ):

        raise RuntimeError(
            "Universe cache schema "
            "is unsupported."
        )

    if not payload.get(
        "stocks"
    ):

        raise RuntimeError(
            "Universe contains no stocks."
        )

    holdings_as_of = (
        payload.get(
            "holdings_as_of"
        )
    )

    if not holdings_as_of:

        raise RuntimeError(
            "Universe cache has no "
            "holdings date."
        )

    age_days = (
        datetime.now(
            timezone.utc
        ).date()

        - date.fromisoformat(
            holdings_as_of
        )
    ).days

    if (
        age_days < -1
        or age_days
        > MAX_UNIVERSE_AGE_DAYS
    ):

        raise RuntimeError(
            "Universe membership is over "
            f"{MAX_UNIVERSE_AGE_DAYS} "
            "days old."
        )

    return payload


# ============================================================
# PUBLIC HELPERS
# ============================================================

def get_stock_universe() -> list[str]:

    return [
        row[
            "symbol"
        ]
        for row
        in load_universe()[
            "stocks"
        ]
    ]


def get_universe() -> list[str]:

    payload = (
        load_universe()
    )

    stocks = {
        row[
            "symbol"
        ]
        for row
        in payload[
            "stocks"
        ]
    }

    benchmarks = set(
        payload[
            "benchmarks"
        ]
    )

    return sorted(
        stocks
        | benchmarks
    )


def get_sector(
    symbol: str,
) -> str | None:

    symbol = (
        symbol
        .strip()
        .upper()
    )

    for row in load_universe()[
        "stocks"
    ]:

        if row[
            "symbol"
        ] == symbol:

            return row[
                "sector"
            ]

    return None


def sector_counts(
    payload: dict | None = None,
) -> dict[str, int]:

    if payload is None:

        payload = (
            load_universe()
        )

    counts = Counter(
        row[
            "sector"
        ]
        for row
        in payload[
            "stocks"
        ]
    )

    return dict(
        sorted(
            counts.items()
        )
    )