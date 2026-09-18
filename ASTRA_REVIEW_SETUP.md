# Astra research-review add-on

## Scope

This is an additive, research-only integration for the existing sector-candidate
pipeline. It does not replace `database.py`, `scanner.py`, `weekly_selector.py`,
`astra_agent.py`, `broker.py`, `config.py`, or any working loader.

The new entry point is `python -m scripts.run_astra_review`. Do not use the old
`run_weekly_selection` placeholder for this checkpoint.

The reader matches the completed `SECTOR_CANDIDATES_CREATED` event written by the
sector-expansion patch. It reads the full frozen candidate packages in that event,
not all mutable rows left over in `weekly_candidates`. Each request stores its input,
schema and instructions, selection ID, prompt version and response usage.

This does not claim to analyze every stock in IVV or predict the best investment.
Astra reviews the supplied shortlist. The default asks for zero to five hypothetical
BUY ideas, plus WATCH/PASS evaluations for every supplied candidate. It can disagree
with Python and select no trades. You can change the requested maximum with
`--max-picks`. Additional-research ideas are not validated stock selections.

## Important limitations

- Market-bar dates/session completeness, corporate-action treatment, event calendars,
  news coverage and portfolio information have NOT been certified by the current
  candidate format. A recently built selection is not proof of fresh prices.
- Since freshness checks were deferred, this is a research pipeline test, not an
  executable current-week buy list. The request and stored results explicitly say so.
- Structured output and source-ID checks do not establish factual accuracy or profits.
  Source IDs refer to supplied articles; the software does not fact-check every claim.
- No model browsing or external tools are enabled. Astra sees the saved articles only.
  It does not use Blossom or train itself from results in this release.
- No account size or holdings are sent. Suggested quantities and numeric confidence
  are stored as NULL. The low/medium/high assessment is not a probability of winning.
- No order, approval, sell, cancellation or portfolio change is implemented here.
  The old order/approval scripts must remain disabled. A `research_only` JSON label is
  documentation, not a security barrier against other processes with DB/broker access.
- This add-on does not install a scheduler. It runs only when you invoke it.

## Files

Add these files to matching folders in the existing repository:

    requirements-astra-review.txt
    ASTRA_REVIEW_SETUP.md
    database/migrations/002_astra_review.sql
    src/astra_review.py
    src/astra_review_store.py
    scripts/init_astra_review.py
    scripts/run_astra_review.py
    scripts/view_astra_review.py
    scripts/test_astra_review.py

Keep the existing `src/__init__.py` and `scripts/__init__.py`.
No existing Python file or database schema.sql is overwritten by this archive.

## Install

1. Stop any order/approval programs. Back up the database using pgAdmin and make a
   clean local Git checkpoint of nonsecret code. Do not upload backups or `.env`.
2. Extract the archive into a temporary directory, then copy the files above into
   the existing repository. Do not replace the whole project directory.
3. Activate the existing virtual environment and run from the repository root:

```powershell
python -m pip install -r requirements-astra-review.txt
```

4. Keep the current Alpaca/PostgreSQL settings. These existing settings are enough:

```env
OPENAI_API_KEY=your_existing_openai_key
ASTRA_MODEL=gpt-6-astra
```

The key is loaded locally from the project `.env` or environment. Do not paste it in
chat. `load_dotenv` does not override a preexisting environment value.

5. Add the following to the root `.gitignore` without deleting existing rules:

```gitignore
# Locally stored model inputs, responses and research results
reports/astra/
```

Check for files already tracked separately; an ignore rule does not untrack them.
The code never writes the API key to input or response artifacts. Research outputs
may still contain private data and should not be committed automatically.

## Test sequence

### A. Offline tests (no API, DB connection or charge)

```powershell
python -m scripts.test_astra_review
```

Expected: `Ran 50 tests ... OK`.
Tests use mocked API responses and mocked database cursors. They cover input selection
IDs, duplicates, missing symbols, malformed model outputs, invented article IDs,
refusals, incomplete results, no-trade output, price geometry, usage estimates,
reasoning-token accounting, dry-run behavior and fixed PENDING inserts.
They are NOT a live API/SDK compatibility test or an executed PostgreSQL migration.

### B. Create only the two new tables

```powershell
python -m scripts.init_astra_review
```

This command checks required existing columns, creates `astra_review_runs` and
`astra_api_usage`, and checks their expected columns in one transaction. It does not
reset tables, reload history or run your old schema.sql. If conflicting custom tables
already exist, stop on the error; do not drop them or reset the database.

### C. Preview the exact request (no OpenAI call)

```powershell
python -m scripts.run_astra_review
```

This reads the latest completed sector selection, reports its selection/scan IDs and
coverage, and writes a local `.input.json` artifact under `reports/astra/`.
It does not add a review-run record or a pending proposal.

Review the displayed selection date and warnings. Do not run the scanner or rebuild
candidates between the preview and the paid request. You can lock the paid request
to the displayed selection UUID with `--selection`.

### D. Explicitly send one billable review

```powershell
python -m scripts.run_astra_review --send
```

Or use the exact selection ID printed in step C:

```powershell
python -m scripts.run_astra_review --send --selection YOUR_SELECTION_UUID
```

Replace `YOUR_SELECTION_UUID` with the actual printed UUID; do not use the literal
placeholder. This makes one generation request to the official OpenAI Responses API.
No broker credentials or tools are used. SDK automatic retries are disabled.
The default is low reasoning effort with a 16,000 output-token limit; the cap includes
reasoning and is NOT a dollar spending cap. The request uses Standard/default service.

Output can be:

- COMPLETED: structured report passed local validation; BUY/WATCH research ideas are
  inserted into `astra_decisions` as PENDING in the same transaction as the report.
  PASS evaluations remain in the full report. Zero BUY ideas is valid.
- INCOMPLETE, REFUSED, INVALID: usage is recorded if supplied, but no proposals are
  inserted. The request can still be billable.
- API_ERROR/UNKNOWN: no proposals. Missing usage is unknown, NOT assumed to be free.
  A timeout can happen after server-side processing. Check API billing before retry.
- SAVE_ERROR: keep the local response copy and fix storage; do not buy another
  generation to repair a database failure. This release has no automatic recovery
  command; the saved response supports manual recovery without a new model call.

### E. Read the report and costs

```powershell
python -m scripts.view_astra_review
```

This shows the most recent attempt, including failures. To inspect a particular one:

```powershell
python -m scripts.view_astra_review --id YOUR_REVIEW_UUID
```

The output includes the shortlist, each evaluation, evidence source IDs/URLs, warnings,
proposed hypothetical levels, per-call usage, and this week's recorded cost range.
The week boundary uses America/New_York. These are not the bot's profit/loss figures.

## Repeating runs

The request fingerprint includes the frozen payload, full request settings, prompt
version and attempt number. Running the exact same command again does not issue
another paid generation if that attempt already exists. This prevents common
accidental duplicates for this runner, not all possible failures or other programs.

Only when you intentionally authorize a NEW generation, change the attempt number:

```powershell
python -m scripts.run_astra_review --send --attempt 2
```

Each attempt can cost money and can generate a different report. Changing a selection,
model or request setting also produces a new fingerprint. A STARTED record after a
crash must be investigated, not treated as permission to retry automatically.

For a deliberate historical study of a selection older than seven days:

```powershell
python -m scripts.run_astra_review --historical --selection YOUR_SELECTION_UUID
```

Add `--send` only after previewing. Historical mode does not make stale data current.

## Pricing and cost accounting

Rates in the estimator were checked on 2026-09-17 against official OpenAI docs:

- Standard short-context GPT-6 Astra input: USD 10 / 1M tokens.
- Cached input: USD 1 / 1M tokens.
- Cache writes: USD 12.50 / 1M tokens.
- Output: USD 50 / 1M tokens.
- Above 272K input tokens, the documented long-context rates apply.

The lower estimate charges noncached input at the input rate. The upper estimate
conservatively treats all noncached input as cache writes. Cached tokens are not
charged twice. Reasoning tokens are part of `output_tokens` and are not added twice.
Raw usage and the rate assumptions are stored so estimates can be reconciled later.

The range is a token-only estimate, not a guarantee of final billing. Regional charges,
taxes, discounts, rate changes, external usage and unknown failed requests can differ.
Unsupported model/tier or missing usage produces NULL costs, not a fabricated $0.
No web/search tool charges are expected from this runner because it exposes no tools.
The weekly display covers ONLY requests recorded by this runner, not connection tests,
other applications or your entire OpenAI project. OpenAI billing is authoritative.
This code does not set a project-wide hard budget or monitor costs in the background.

Sources:
https://developers.openai.com/api/docs/models/gpt-6-astra
https://developers.openai.com/api/docs/guides/structured-outputs
https://developers.openai.com/api/docs/guides/reasoning
https://developers.openai.com/api/docs/pricing

## Known follow-on work before any execution

Validate daily-bar timestamps and completed sessions; align candidate and benchmark
windows; handle feed differences and corporate actions; verify upcoming events;
include actual portfolio state; construct an exact paper order with expiry; bind
human approval to all order fields; enforce transaction-safe submission/idempotency;
reconcile fills and errors; establish suitable access permissions and limits.
None of those execution steps is bypassed by a PENDING research recommendation.
