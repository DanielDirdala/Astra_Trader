# Astra Trader - consolidated v0.2

This version is based on your actual `Astra_Trader-main.zip`, not an assumed stack
of previous patches. **Do not install the old profit-objective or finalist ZIPs
before or after this version.** Their compatible functionality is consolidated here.

## Important findings

Your uploaded code already contains `us_market_ops.py`, `paper_tickets.py`, the
US-market migration, sector expansion, the Astra review store, and a saved universe
of 503 equity entries. Presence of code/universe files does not establish the
state of your running database. No `.env`, `.git`, `.venv`, API key pattern, or
hard-coded long password assignment was detected in this archive. The automated
check is not a guarantee that every possible secret format was identified.

## Supported workflow

```text
Python: incremental daily sync -> numerical sector screen -> news/current snapshots
                                      |
                             up to 3 finalists
                                      |
                       GPT-6 Astra (only on --send)
                                      |
                         0-2 hypothetical BUY ideas
                                      |
                        PENDING research records
                                      |
               separate exact-order HUMAN approval -> Alpaca PAPER
```

Use one entry point: `python -m scripts.trader`. `--help` lists commands.
The smaller finalist selector is a heuristic using the existing numerical score;
it is NOT a trained predictive model. It can miss better opportunities elsewhere.
The earnings calendar and Blossom remain unconnected and visibly labeled missing.

## Quick start

Follow `INSTALL.md`. Do not discard your original repo or PostgreSQL history.

```powershell
python -m pip install -r requirements.txt
python -m scripts.trader test
python -m scripts.trader doctor --db
python -m scripts.trader usage
```

No dependency installation happened in the creator's testing environment. Review
`TEST_REPORT.txt` for actual test scope, package availability and limitations.

## Routine research

```powershell
python -m scripts.trader sync
python -m scripts.trader capture
python -m scripts.trader review --context CONTEXT_UUID
# Only after reviewing the preview, and only when the spending guard permits:
python -m scripts.trader review --context CONTEXT_UUID --send
python -m scripts.trader report
```

- `sync`: public data GET requests + PostgreSQL writes. No model call or order.
- `capture`: numerical screening, news/current snapshots and paper-account GETs;
  context stored locally/PostgreSQL. No model call or order.
- `review` without `--send`: local/DB preview. No OpenAI request.
- `review --send`: sends the compact market/news/account input to OpenAI's input
  count endpoint, then (only within limits) makes one billable model generation.
  No API keys or account ID are included. No web tools or order tools exposed.
- `usage`/`report`: read recorded research records; no model call or order.

Captures must be <=5 minutes old. At an open market, finalist quotes must still
meet the quote-age check before the request. Off-hours research is hypothetical.
Any later order preparation requires the original recent-context checks as well.
No stale report is silently converted into a fresh execution instruction.

## Cost controls

The defaults in `.env.example` restrict reviews to at most 3 finalists (maximum 2
from a sector), 3 recent distinct news excerpts each, and at most 2 BUY ideas. Shared
benchmark context is sent once. Reasoning effort is `low` and total output is capped
at 4,000 tokens, INCLUDING reasoning. A truncated response may still be billed and
creates no proposals. There is no automatic generation retry.

A formatted input-token count is requested before generation. Input cap is 8,000
and planned per-call token allowance is $0.35. The allowance uses the published
Standard short-context cache-write rate for all input, maximum output, plus 10%
planning headroom. It is NOT an invoice guarantee or account-wide spending limit.

Default rolling budget: $1 over 7 days, maximum 2 recorded attempts, 6-hour cooldown.
Recorded earlier reviews count. A recorded $1.02 in the window blocks another
review: that is intentional. Inspect with `usage`; wait or deliberately change
`ASTRA_BUDGET_7D_USD` in YOUR .env. Do not delete usage records to bypass a guard.
Unresolved prior requests block generation, including unresolved requests older
than 7 days. Unknown costs are never treated as zero. Manual calls, API connection
tests, other apps/projects, taxes, and unrecorded usage are not controlled here.

Budget claims are serialized by a PostgreSQL transaction advisory lock with a
15-second wait limit, and written before generation. After a timeout, inspect the
record/dashboard rather than repeatedly issuing a new request. Local response
backups support investigation, but automated response/unknown-charge recovery is
not implemented.

Prices checked on 2026-09-18: GPT-6 Astra Standard input $10/1M, cached input $1/1M,
cache writes $12.50/1M, output $50/1M. They are configuration assumptions, not a
permanent guarantee. No automatic model substitution. For example, 6,000 ordinary
input + 2,000 total output tokens is $0.16 in token arithmetic; your bill depends on
actual usage/cache/tier and other charges. See `SOURCES.md`.

## History efficiency and preservation

The uploaded repo ALREADY had batched/incremental updates. This version preserves
that cache and improves request grouping: new-symbol long backfills are not placed
in the same request as nearly-current symbols. It retries recent missing sessions,
retains a short correction overlap, and uses batch `executemany` writes. Identical
bars do not incur unnecessary row updates. No wall-clock speedup is claimed until
measured on your machine.

The cache key separates symbol/feed/adjustment/session. Never mix IEX/SIP or raw/
split-adjusted series. The initial 450-session backfill is for warm-up; adopted
250-session series can remain usable. Daily sync is not another full 450-bar load.
A periodic (default weekly) reconciliation still intentionally fetches a longer
window for revisions. Current intraday observations remain separate from completed
daily features; partial-day volume is not full-day relative volume.

Legacy adoption is optional and explicit:

```powershell
python -m scripts.trader adopt-legacy
# Only if you KNOW the old bars were IEX with adjustment=raw:
python -m scripts.trader adopt-legacy --confirm-iex-raw-provenance
```

Original `market_snapshots` rows are never deleted. If the operational cache already
contains that data, no adoption is needed. Feed provenance cannot be inferred from
raw price values. Your older `load_history`/`run_scanner` scripts remain historical
compatibility utilities, not the preferred efficient workflow.

## $100-$200 objective: planning/reporting, NOT strategy or sizing

Capital, loss tolerance and weekly-versus-biweekly preference were not specified.
No capital is guessed from Alpaca's paper margin buying power. No risk limit is
increased to pursue the target, and the target is not included in the model prompt.

```powershell
# Offline example using $5,000 only as an illustration, not advice:
python -m scripts.trader goal --capital 5000 --days 14 --costs 1
# Read actual PAPER activities; all API/data costs for the period must be supplied:
python -m scripts.trader pnl --days 14 --capital 5000 --costs 1
```

`pnl` reads all returned account activity since account creation so older opening
lots can be matched to sales during the rolling 7/14 NY-calendar-day window. It is
an explicit long-only FIFO research estimate, not Alpaca/tax cost-basis accounting.
Deposits and dividends are not counted as trading profits. Unrealized P&L is shown
separately as current since-entry P&L, NOT profit earned within the reporting period.
It covers manual and other-program paper trades too, not just this bot.

Missing opening lots, unsupported corporate actions/transfers, conflicting fills,
or position reconciliation mismatches invalidate the realized estimate. Returns
of capital are not silently ignored. Unknown external costs mean net-after-costs
is unknown. Broker fees may post later; endpoint reads are not atomic. Check the
broker statement. No result is a promise of earning $100-$200.

## Paper execution remains manual and disabled by default

`ASTRA_ENABLE_PAPER_SUBMISSION=false` is the default, including when the variable
is absent. To intentionally enable the existing PAPER executor, set it to `true`
in your local .env AFTER the diagnostics and research tests are verified.

```powershell
python -m scripts.trader paper prepare --review REVIEW_UUID --symbol SYMBOL --qty 1
python -m scripts.trader paper submit TICKET_UUID --ack-earnings-unknown
python -m scripts.trader paper status TICKET_UUID
```

The submission command requires the displayed exact `APPROVE PAPER ...` phrase.
It does not infer approval from Astra's recommendation or old DB APPROVED flags.
Only long, whole-share, cash-funded, regular-session limit bracket entries are
supported. The inherited $1,000 paper-test notional cap is NOT increased; it is an
operational maximum, not a recommendation about your real capital. Stops cannot
guarantee a maximum loss. The 5-minute submission deadline is not an order TTL:
a submitted GTC entry can remain open until filled/canceled. Partial entries can
be unprotected until the broker activates the bracket exits. No automatic stale
entry canceler, full exit manager, continuous loss service, or live trading is added.

Stop old workers before using this version. Direct legacy Broker submit methods and
TradeManager execution are disabled. Current `us_market review` / `daily_us_research`
commands route to the SAME guarded finalist engine. Historical `run_astra_review
--send` now refuses before doing work. Deliberately writing new SDK calls can still
bypass application controls; these controls are not a security sandbox.

## Module map

- `scripts/trader.py`: supported command router; lazy imports.
- `src/us_market_ops.py`: existing efficient cache + current market context.
- `src/research_engine.py`: one finalist selector, compact input, token/budget guards.
- `src/ops_review.py`: context contract and existing review storage adapter.
- `src/astra_review.py` / `astra_review_store.py`: structured validation and persistence.
- `src/pnl_tracker.py` / `profit_tracking.py`: independent local planning/read-only P&L.
- `src/paper_tickets.py`: explicit PAPER order approval/execution, never called by research.
- `src/project_health.py`: schema/types diagnostic and optional additive initialization.

No Blossom access, earnings feed, trained strategy, no-loss guarantee or profit
validation is asserted. Old setup guides are labeled historical. This README and
INSTALL.md take precedence for this consolidated build.
