> HISTORICAL GUIDE: README.md and INSTALL.md describe the consolidated v0.2 workflow.
> Do not apply older ZIPs or use broad historical paid-review instructions below.

# Astra US market operations - paper prototype v1

## Scope and safety boundary
This is an ADDITIVE upgrade to the prior sector-expansion and research-review add-ons.
It is not a live-money bot or a validated profitable strategy. There is no live endpoint switch.
New entries require a separately prepared exact-order ticket and typed local human approval.
The daily research helper can refresh data, screen the universe, fetch news and request one
model review. It cannot approve or submit orders. After you approve a bracket order, Alpaca
manages its conditional exit orders according to the broker's documented rules.

Keep the earlier broker.py/trade_manager.py/approval_manager.py order scripts disabled.
They do not share this ledger or these controls. The local PostgreSQL user is still an
administrator in many development installations: JSON flags or hashes are not access
controls against another process with that user's credentials. Separate service roles,
real deployment hardening and independent testing are still needed before production.

## Existing work is preserved
No old files are replaced and no legacy tables are truncated or rebuilt. The new cache
stores daily OHLCV by symbol, feed, adjustment and session date. Original market_snapshots
remain unchanged. The new capture command computes its own updated numerical screen from
the cache. Do not expect the old scanner to automatically read the new cache; use this
new command sequence for the current-data workflow. Sector membership comes from your
existing data/universe.json via the sector patch. The old review add-on supplies the
strict response model, response validation, API usage logging and report viewer.

Files to add:
- requirements-market-ops.txt
- database/migrations/003_market_operations.sql
- src/us_market_ops.py
- src/ops_review.py
- src/paper_tickets.py
- scripts/us_market.py
- scripts/paper_order.py
- scripts/daily_us_research.py
- scripts/test_market_ops.py

## Install and test
Back up PostgreSQL first and stop old loaders/order workers. From your repo root:

    python -m pip install -r requirements-market-ops.txt
    python -m scripts.test_market_ops
    python -m scripts.us_market init

The tests are offline mocks, not a live-broker or real-PostgreSQL certification.
This release was syntax checked and its offline tests run in the authoring environment.
Live Alpaca calls, local database integration, and real model latency need testing on your machine.

Add to .gitignore (do NOT remove existing secret exclusions):

    reports/market_ops/
    reports/astra/

Add optional configuration to your existing .env; do not share actual keys:

    OPS_FEED=iex
    OPS_ADJUSTMENT=raw
    OPS_BATCH_SIZE=20
    OPS_QUOTE_MAX_AGE_SECONDS=60
    OPS_PAPER_MAX_ORDER_USD=1000

These are prototype operational limits, not personalized investment allocations.
PAPER endpoint is hardcoded regardless of the legacy PAPER_TRADING setting.
Quote freshness is exchange-event timestamp age, not HTTP download time.

## Reuse earlier history without repeating the initial download
Only use this command when the legacy bars were actually fetched from IEX with no
adjustment (the defaults in the previous supplied loader). This is a USER ATTESTATION,
not an independently verified provenance certificate. Mixed or unknown data should be
fetched afresh instead. The preview does not copy anything:

    python -m scripts.us_market adopt-legacy

After confirming that origin:

    python -m scripts.us_market adopt-legacy --confirm-iex-raw-provenance

This copies eligible raw daily rows into the new cache; it does not delete or reclassify
the originals. Indicators are recomputed; early or incorrectly computed legacy indicators
are not reused. The copy count reports examined rows, not guaranteed newly inserted rows.

Test a few stocks and benchmarks, then all universe members:

    python -m scripts.us_market sync --symbols AAPL,JNJ,JPM,SPY,QQQ
    python -m scripts.us_market sync

Batch requests reuse one HTTP session. All next_page_token values are followed.
GET retries are bounded, paced and limited to rate-limit/temporary transport errors.
API permission/feed errors do not silently fall back to another feed.
Database writes use executemany and one commit per batch, not a new connection per bar.
Successful batches remain committed if a later batch fails. The next run plans from
persisted data rather than starting over. Up-to-date symbols recently checked are skipped.
Typical subsequent work is missing sessions plus five-session overlap, not a complete
history download. A periodic full refresh handles older revisions; failed symbols remain
reported as failures. No bars/NaNs are invented or forward-filled.

A fresh backfill requests 450 trading sessions (when available), allowing indicator warm-up.
Adopted 250-session series can work without forcing that initial full download. The feature
engine uses up to the latest 450 bars and requires 201 aligned daily sessions for screening.
New listings or illiquid/missing-session series can be excluded and are listed in the context.
It does not assume all source securities have the same history coverage.

Periodic full reconciliation is due after seven days, including eventually for adopted
series. If OPS_ADJUSTMENT=split and overlapping historical values change, the rolling
window is fetched again before using mixed adjusted values. No source can guarantee all
revisions are discovered instantly. Raw data can include splits and other corporate-action
jumps; the model receives that warning. Changing feed or adjustment starts a SEPARATE
cache series and may require a new backfill. Never attest old IEX/raw rows as SIP/split.

## Completed daily data vs current activity
The daily cache intentionally excludes the current NEW YORK calendar date, even after
regular trading closes. This is conservative: a provider daily aggregate can change after
RTH close. Calendar holidays are excluded and sessions are aligned to the same target.
Current-day behavior is supplied separately as a timestamped snapshot with trade, quote,
minute bar, daily bar and prior daily bar. Quotes and trades have independent timestamps.
Intraday daily bars are not fed into the historical SMA/ATR/RSI calculation. Full-day
average volume is not treated as a time-of-day volume baseline.

## Capture, preview, review

    python -m scripts.us_market capture
    python -m scripts.us_market review --context CONTEXT_UUID
    python -m scripts.us_market review --context CONTEXT_UUID --send

Replace CONTEXT_UUID with the printed context ID. Review requires a capture <=5 minutes
old. Read the preview before using --send. Capture fetches the entire current cached
universe's numerical features, picks up to 3 per sector + 5 extra globally, fetches capped
recent news, then PAPER account/positions/orders and fresh market snapshots. SPY/QQQ live
snapshots accompany their daily benchmark features. Only the shortlist receives model
review; the coverage report names exclusions. The model has no broker or browser tools.

Capture works when the market is closed, but then quotes are not labelled executable.
News failure is distinct from no articles. No earnings calendar or Blossom feed is inferred.
The account summary/holdings/open orders and news are transmitted to OpenAI only with
review --send. Account ID and API keys are not in the model input. Model requests are
billable; the SDK is not automatically retried. Identical recorded attempts are not resent.
A new context is a new request and can incur another charge. The existing usage logger is
reused; billing estimates are not invoices, spending caps, or a guarantee about unknown
transport failures. Inspect API billing for authoritative charges.

View the model report with the previously installed command:

    python -m scripts.view_astra_review

Current reviews store the context ID, exact input, prompt and PENDING research rows.
Old historical-only reviews cannot be turned into paper tickets by this helper.

## Prepare one exact paper entry
FIRST test the entire data and review path. Paper order support is intentionally narrow:
- LONG entries only, positive whole shares, prices >= $1 with <=2 decimals
- limit bracket, GTC, no extended-hours submission
- active tradable US equity, regular calendar hours including early close
- quote <= configured age, spread <=50 bps, entry within 3% of current midpoint
- cash after conservative reservation for other open buys, no use of margin
- no existing position or open order in the same symbol
- configured per-order notional test cap (default $1,000)
- one ticket per review/symbol; five-minute submission approval window

A model BUY must include a valid entry, stop and target; missing fields fail, never get
invented. The current context must be <=15 minutes old at preparation. If analysis took
longer, obtain new context; do not edit timestamps to defeat the check.

    python -m scripts.paper_order prepare --review REVIEW_UUID --symbol SYMBOL --qty 1

Replace REVIEW_UUID and SYMBOL with a completed current-context review and one of its
BUY proposals. You choose the exact share count. Preparation makes no order request.
Inspect the exact saved limit/stop/target, quantity, cash reservation and quote checks.

Earnings calendar integration is NOT completed. For PAPER prototype testing only, review
that risk and acknowledge the known gap explicitly:

    python -m scripts.paper_order submit TICKET_UUID --ack-earnings-unknown

Then type the entire requested APPROVE PAPER <ticket UUID> phrase. This is consequential:
it sends one actual SIMULATED order to Alpaca. It is NOT a live-money order.
The checks are repeated after approval. Symbol/quantity/prices cannot change without a
new ticket. No auto-approval exists. The model never receives this function as a tool.

A global local-worker lock plus durable SUBMITTING state is committed before the POST.
The POST is sent once. A timeout/rejection/uncertain response becomes UNKNOWN; no automatic
order retry. Lookup uses the same client_order_id. UNKNOWN blocks other new entries until
you investigate it; a 404 alone is not proof the submission never arrived. Do not create
another client ID to bypass uncertainty. This prototype has no automatic ambiguity-clear
operation: use the dashboard and fix the confirmed cause before extending the ledger logic.

## Monitor after submission

    python -m scripts.paper_order status TICKET_UUID
    python -m scripts.paper_order watch TICKET_UUID --seconds 30

The watch loop runs only while YOUR local process runs. Ctrl+C stops observation, NOT
broker orders. Confirm the order and its legs in the Alpaca paper dashboard.

IMPORTANT: submitted/accepted is not filled. Bracket exits activate only after the entry
fills completely. Partial entries can be temporarily unprotected. The monitor warns but
does not automatically liquidate. Stop orders do not guarantee stop-price fills and bracket
cancellations can race. Exits here are not enabled for extended hours; overnight gaps remain.
An approved GTC ENTRY can stay pending across sessions until canceled/filled/expired by
the broker. The five-minute approval window is ONLY a pre-submission limit; it does not
cancel an accepted order. Stale entry cancellation and advanced position management are
not implemented. Do not leave this prototype fully unattended.

Creating an empty STOP_TRADING file in the repo blocks new entries. It does not cancel
existing orders or close positions. Perform those actions deliberately in Alpaca.

## Local automation, not an invisible ChatGPT background job

    python -m scripts.daily_us_research

Runs one synchronous sync/capture/preview cycle; no model request. After validating it:

    python -m scripts.daily_us_research --send

Runs one research cycle with one model call, then stops. It never submits orders. A local
scheduler can launch this on market mornings, but none is installed by this patch. Your
computer must be running. Do not schedule overlapping jobs, unbounded model calls, or the
interactive order-submission command. The paper watch loop has no model/API-token costs
but uses Alpaca read requests. Push/email notifications are not configured; output is local.

## Not solved by this release
- No permissioned Blossom feed/API/plugin, no scraping or cookie reuse.
- No verified upcoming earnings calendar. A paper-only acknowledgment is NOT verification.
- No trained trading policy or demonstrated predictive edge. This configures the workflow;
  it does not fine-tune GPT weights. Evaluate out of sample and separate wins from selection
  bias, feed differences, costs and correlated observations.
- Not a real-money deployment: no complete reconciliation service, automatic handling of
  partial entries/stale GTC entries, intraday portfolio loss circuit breaker, secrets vault,
  continuously running alert service, or independent production audit.
- Paper fills are not real exchange fills. IEX quotes are not consolidated NBBO coverage.
- No exhaustive news or all-market model analysis. Extra data is not guaranteed accuracy.

## Primary documentation reviewed
Alpaca multi-symbol historical bars:
https://docs.alpaca.markets/us/reference/stockbars
Alpaca snapshots:
https://docs.alpaca.markets/us/reference/stocksnapshots-1
Alpaca calendar:
https://docs.alpaca.markets/us/reference/legacycalendar
Alpaca orders and bracket behavior:
https://docs.alpaca.markets/us/docs/orders-at-alpaca
Alpaca paper simulation:
https://docs.alpaca.markets/us/docs/paper-trading
Alpaca data plans:
https://docs.alpaca.markets/us/docs/about-market-data-api
Psycopg pipeline/executemany:
https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html
Blossom current terms:
https://www.blossomsocial.com/terms
