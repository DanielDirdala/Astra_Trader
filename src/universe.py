"""Versioned sector universe; imports perform no network requests or trades.

The public fund-holdings file is a research-universe source, NOT a price feed,
not a recommendation, and not point-in-time historical index membership.
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

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "data" / "universe.json"
ARCHIVE_DIR = ROOT / "data" / "universe_snapshots"
BENCHMARKS = ["SPY", "QQQ", "IWM", "DIA"]
MAX_UNIVERSE_AGE_DAYS = 14

SOURCES = {
    "IVV": {
        "url": "https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv",
        "minimum_equities": 300,
    },
    "ITOT": {
        "url": "https://www.ishares.com/us/products/239724/ishares-core-s-p-total-u-s-stock-market-etf/latest-holdings.csv",
        "minimum_equities": 1000,
    },
}

SECTORS = {
    "Information Technology", "Health Care", "Financials", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Communication Services",
    "Energy", "Utilities", "Materials", "Real Estate",
}


def parse_holdings(text: str, minimum_equities: int = 300) -> tuple[str, list[dict]]:
    """Read the provider's CSV, including its preamble and quoted commas."""
    header = None
    holdings_date = None
    records: dict[str, dict] = {}
    for values in csv.reader(io.StringIO(text.lstrip("\ufeff"))):
        values = [value.strip() for value in values]
        if not values or not any(values):
            continue
        if header is None:
            if values[0].lower() == "fund holdings as of" and len(values) > 1:
                for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
                    try:
                        holdings_date = datetime.strptime(values[1], fmt).date()
                        break
                    except ValueError:
                        continue
            if {"Ticker", "Name", "Sector", "Asset Class"}.issubset(values):
                header = values
            continue
        if len(values) != len(header):
            continue  # Skip legal footers, not incomplete stock records.
        row = dict(zip(header, values))
        if row["Asset Class"].casefold() != "equity":
            continue  # Cash, futures, and money-market holdings are not stocks.
        ticker = row["Ticker"].upper()
        sector = {"Communication": "Communication Services"}.get(row["Sector"], row["Sector"])
        if not ticker or ticker == "-" or sector not in SECTORS:
            raise ValueError(f"Unrecognized equity identifier/sector: {ticker!r}, {sector!r}")
        if ticker in records:
            raise ValueError(f"Duplicate equity ticker in source: {ticker}")
        records[ticker] = {
            "source_symbol": ticker,
            "name": row["Name"],
            "sector": sector,
            "industry": None,  # This source supplies sectors, NOT sub-industries.
        }
    if header is None or holdings_date is None:
        raise ValueError("Holdings CSV layout/date could not be recognized; existing cache is unchanged.")
    if len(records) < minimum_equities:
        raise ValueError(f"Only {len(records)} equities parsed; expected at least {minimum_equities}.")
    return holdings_date.isoformat(), sorted(records.values(), key=lambda row: row["source_symbol"])


def symbol_variants(symbol: str) -> list[str]:
    """Handle class-share notation only when a matching broker asset exists."""
    original = symbol.strip().upper()
    variants = [original]
    if re.fullmatch(r"[A-Z]+[ .\-/][A-Z]", original):
        base, share_class = re.split(r"[ .\-/]", original)
        variants.extend([f"{base}.{share_class}", f"{base}-{share_class}", f"{base}/{share_class}"])
    return list(dict.fromkeys(variants))


def match_assets(records: list[dict], assets: Iterable[Any]) -> tuple[list[dict], list[dict], list[str]]:
    """Accept only active, tradable US-equity symbols returned by Alpaca."""
    def field(asset: Any, key: str) -> Any:
        value = asset.get(key) if isinstance(asset, dict) else getattr(asset, key, None)
        return getattr(value, "value", value)

    available = {}
    for asset in assets:
        if (field(asset, "status") == "active"
                and field(asset, "asset_class") == "us_equity"
                and field(asset, "tradable") is True):
            available[str(field(asset, "symbol")).upper()] = asset
    accepted, excluded = [], []
    used = set()
    for record in records:
        matches = [symbol for symbol in symbol_variants(record["source_symbol"]) if symbol in available]
        if not matches:
            excluded.append({**record, "reason": "No matching active/tradable Alpaca US equity"})
            continue
        # Distinct matching variants are ambiguous; never guess a security.
        if len(matches) != 1:
            excluded.append({**record, "reason": "Ambiguous class-share notation", "matches": matches})
            continue
        symbol = matches[0]
        if symbol in used:
            raise ValueError(f"Multiple source records resolved to {symbol}; refusing ambiguous universe.")
        used.add(symbol)
        accepted.append({**record, "symbol": symbol})
    benchmarks = [symbol for symbol in BENCHMARKS if symbol in available]
    if not {"SPY", "QQQ"}.issubset(benchmarks):
        raise ValueError("SPY and QQQ were not verified as active/tradable benchmark assets.")
    return sorted(accepted, key=lambda row: row["symbol"]), excluded, benchmarks


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def refresh_universe(fund: str = "IVV") -> dict:
    """Download public holdings and validate assets. Never submit an order."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest
    from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

    fund = fund.upper()
    if fund not in SOURCES:
        raise ValueError("fund must be IVV or ITOT")
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise ValueError("Alpaca paper credentials are missing from config/.env.")
    source = SOURCES[fund]
    retry = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(source["url"], timeout=(10, 60))
        response.raise_for_status()
        if len(response.content) > 15_000_000:
            raise ValueError("Unexpectedly large holdings response; refusing to parse.")
        as_of, records = parse_holdings(response.content.decode("utf-8-sig"), source["minimum_equities"])
    age = (datetime.now(timezone.utc).date() - date.fromisoformat(as_of)).days
    if age < -1 or age > MAX_UNIVERSE_AGE_DAYS:
        raise ValueError(f"Source holdings date {as_of} is stale or in the future; existing cache unchanged.")
    client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    assets = client.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))
    stocks, excluded, benchmarks = match_assets(records, assets)
    if len(stocks) < source["minimum_equities"]:
        raise ValueError(f"Only {len(stocks)} eligible assets matched; existing cache unchanged.")
    if {row["sector"] for row in stocks} != SECTORS:
        raise ValueError("Not all 11 sectors survived validation; existing cache unchanged.")
    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": 1,
        "universe_id": str(uuid4()),
        "fund": fund,
        "source_url": source["url"],
        "holdings_as_of": as_of,
        "refreshed_at": now.isoformat(),
        "source_equities": len(records),
        "stocks": stocks,
        "benchmarks": benchmarks,
        "excluded": excluded,
    }
    # Archive metadata for future membership audits. The cache has no prices/keys.
    archive = ARCHIVE_DIR / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}_{fund}.json"
    _write_json_atomic(archive, payload)
    _write_json_atomic(UNIVERSE_PATH, payload)
    _read_cached.cache_clear()
    return payload


@lru_cache(maxsize=4)
def _read_cached(path: str, modified_ns: int) -> dict:
    del modified_ns
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_universe() -> dict:
    if not UNIVERSE_PATH.exists():
        raise RuntimeError("No dynamic universe exists. Run: python -m scripts.refresh_universe --fund IVV")
    payload = _read_cached(str(UNIVERSE_PATH), UNIVERSE_PATH.stat().st_mtime_ns)
    if payload.get("schema_version") != 1 or not payload.get("stocks"):
        raise RuntimeError("Universe cache is invalid. Re-run scripts.refresh_universe.")
    age = (datetime.now(timezone.utc).date() - date.fromisoformat(payload["holdings_as_of"])).days
    if age < -1 or age > MAX_UNIVERSE_AGE_DAYS:
        raise RuntimeError("Universe membership is over 14 days old. Re-run scripts.refresh_universe.")
    return payload


def get_stock_universe() -> list[str]:
    return [row["symbol"] for row in load_universe()["stocks"]]


def get_universe() -> list[str]:
    payload = load_universe()
    return sorted({row["symbol"] for row in payload["stocks"]} | set(payload["benchmarks"]))


def get_sector(symbol: str) -> str | None:
    return next((row["sector"] for row in load_universe()["stocks"]
                 if row["symbol"] == symbol.upper()), None)


def sector_counts(payload: dict | None = None) -> dict[str, int]:
    data = payload if payload is not None else load_universe()
    return dict(sorted(Counter(row["sector"] for row in data["stocks"]).items()))
