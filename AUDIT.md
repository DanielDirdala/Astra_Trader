# Audit of the uploaded repository

Source: `Astra_Trader-main.zip` (SHA256 `3585c3832a2a243247bd4f90ffbda79b7dd9696a855c80381d28cb56e8d071a4`).

## Actual starting state

The uploaded tree already includes `src/us_market_ops.py`, `src/ops_review.py`,
`src/paper_tickets.py`, and `database/migrations/003_market_operations.sql`.
Therefore the prior claim that the US-market upgrade still needed installing was
incorrect. `astra_profit_objective.zip` is NOT a prerequisite for this build.

The saved universe contains 503 equity entries. This is membership metadata, not
proof that 503 histories are downloaded, current, or passed the scan. PostgreSQL
rows, recent scan contents, billing records, positions and .env were not in the
archive; their runtime state cannot be inferred from source files.

The ZIP contained neither .env, .git, .venv nor report artifacts. A limited regex
scan found no obvious live-key patterns or hard-coded long passwords. This does
not rule out every possible sensitive value; review your own files before commits.

## Findings addressed

1. `ops_review.review_context` permitted 16,000 output tokens and forwarded the
   sector shortlist with repeated benchmark context. It now delegates to one
   3-finalist engine with 4,000 total output tokens, compact news and shared context.
2. Multiple model runners could generate outside the cost guard. Current-market
   aliases now use the same guard; historical broad `--send` refuses. The standalone
   API connection probe now retrieves model metadata instead of generating text.
3. Initial backfill and incremental symbols could share the same broad date range.
   The syncer now groups requests by their actual start date before batching.
4. Identical bars caused unnecessary conflict updates. Batch SQL now avoids row
   updates when bar/provenance/timestamp are unchanged. It still checks overlaps.
5. Recent missing sessions in a mostly populated series were not revisited until
   a full refresh in some cases. A daily gap retry was added; no forward filling.
6. A malformed news response could look like zero articles. Missing/non-list news
   data now raises an explicit retrieval error.
7. The mutable `APPROVED`/caller-quantity legacy executor bypassed exact-ticket
   authorization. It and legacy direct Broker order methods are disabled. The
   existing paper-ticket code remains the only supported submission path and
   requires an explicit enabling flag plus exact typed approval.
8. Order preparation could accept a future context timestamp and a ticket could
   expire during preflight. Both boundaries are checked explicitly now.
9. Per-row DSN string construction in the legacy Database client mishandled special
   password characters. It now uses Psycopg keyword connection arguments.
10. Defaults could load .env from an unintended working directory. Config resolves
    the project-local .env explicitly (normal environment-variable precedence is retained).

## Deliberate scope decisions

- Selected P&L logic from the profit-objective ZIP was integrated as a read-only
  research ledger. Its alternative model adapter, automatic position sizing and
  competing context contract were NOT installed.
- Profit target stays in the planning/reporting command, never the research prompt
  or order sizing. Real capital, loss tolerance and preferred period are still
  unspecified by the user. Default paper order cap is unchanged.
- No new database schema change is required for these additions. Existing SQL files
  are retained. The new initializer is optional if the read-only doctor passes.
- No trained model, proven trading edge, current earnings calendar, Blossom feed,
  live account access, full exit manager or unconditional autonomous trading added.
- The historical/current caches are not merged without explicit IEX/raw attestation.
- Existing order approval data, prices, reviews and usage logs are never reset.

## Reproduction and changes

Use the top-level installer preview. It compares every changed code file against
this uploaded baseline, allows LF/CRLF checkout differences but refuses other conflicting local edits, and skips all data/secret
paths. It does not act as a migration or dependencies installer.

See `TEST_REPORT.txt` for actual testing limitations. The package hash manifest is
for accidental corruption detection, not a cryptographic publisher signature.

### Modified files

- `.gitignore`
- `ASTRA_REVIEW_SETUP.md`
- `MARKET_OPS_SETUP.md`
- `TEST_REPORT.txt`
- `config.py`
- `requirements-astra-review.txt`
- `requirements-market-ops.txt`
- `requirements.txt`
- `scripts/daily_us_research.py`
- `scripts/run_astra_review.py`
- `scripts/test_astra_connection.py`
- `scripts/test_market_ops.py`
- `scripts/us_market.py`
- `src/broker.py`
- `src/database.py`
- `src/ops_review.py`
- `src/paper_tickets.py`
- `src/trade_manager.py`
- `src/us_market_ops.py`

### Added files

- `.env.example`
- `INSTALL.md`
- `README.md`
- `SOURCES.md`
- `scripts/test_all.py`
- `scripts/test_consolidated.py`
- `scripts/test_profit_tracking.py`
- `scripts/test_research_engine.py`
- `scripts/trader.py`
- `src/pnl_tracker.py`
- `src/profit_tracking.py`
- `src/project_health.py`
- `src/research_engine.py`
