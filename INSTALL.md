# Install onto the repo you uploaded

Do NOT install `astra_profit_objective.zip`, `astra_finalist_cost_saver.zip`, or
`astra_low_cost_finalists_patch.zip` first. This package is built against the actual
uploaded repo, which already has the US-market upgrade.

## 1. Stop jobs and back up

Stop research workers/scheduled tasks and trading workers. Back up PostgreSQL in
pgAdmin before any optional database initialization. Keep your current repository.
Never place the backup, .env or a virtual environment in GitHub.

## 2. Extract this ZIP to a temporary folder

At the extracted top level you should see:

```
apply_upgrade.py
UPGRADE_MANIFEST.json
Astra_Trader/
```

The directory `Astra_Trader/` contains the full synchronized repo without secrets.
Do NOT point the installer at this temporary directory. It must point to your
existing clone. Do not delete the clone or overwrite its .git/.venv/.env.

## 3. Preview the code changes

From the temporary extracted top level in PowerShell (adjust the real path):

```powershell
python .\apply_upgrade.py --repo "C:\Users\Daniel\Documents\Astra_Trader"
```

The installer checks hashes against the uploaded baseline. It lists ADD/UPDATE
operations without changing files. LF/CRLF checkout differences are allowed; other source edits are not. If you edited an affected file after uploading,
it stops before writes rather than guessing how to merge your edits. It does not
print file contents or secret values.

## 4. Apply the verified changes

```powershell
python .\apply_upgrade.py --repo "C:\Users\Daniel\Documents\Astra_Trader" --apply
```

Changed code is backed up outside the repo in a timestamped `_code_backup_...`
folder. Existing data/, reports/, .env, .git and .venv are protected. The installer
does not install packages, run SQL, contact an API or place an order. It does not
change PostgreSQL files. Unchanged source files are not copied over your files.

An interrupted installer can be restored from its code backup. Do not roll back
order/usage records or delete usage data to bypass approval/budget controls.

## 5. Install dependencies and test locally

Return to the EXISTING repo root:

```powershell
cd "C:\Users\Daniel\Documents\Astra_Trader"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m scripts.trader test
python -m scripts.trader doctor --db
```

No exact environment lock is claimed: tests here were Python 3.13 with available
scientific libraries and mocked provider/database boundaries. Dependencies should
be installed on your machine. Capture a `pip freeze` after your own verification.

`doctor --db` is read-only and reports missing columns/types rather than asking you
to reset the DB. Your uploaded SQL already includes all tables this version needs.
If it reports missing tables and you have backed up, run:

```powershell
python -m scripts.trader init
python -m scripts.trader doctor --db
```

Initialization applies existing migrations plus schema in one transaction and
checks original/cache row counts. No destructive reset, new P&L table or re-download
is required by the consolidation itself. Actual server integration must be tested
locally. Do not ignore a failed schema check.

## 6. Keep your .env and inspect costs

Do not copy .env.example over .env. It is only a blank template. Existing credentials
remain unchanged. The new settings have safe defaults, so adding them is optional.
Merge only the settings you deliberately want to change.

```powershell
python -m scripts.trader usage
```

If the prior $1.02 is in the recorded last-seven-day window, another review will
be blocked by the $1 default. This is expected. Wait or deliberately select a new
budget. All unknown/unresolved requests need investigation, not deletion/retry.

## 7. Test research before paper orders

```powershell
python -m scripts.trader sync --symbols AAPL,JNJ,JPM,SPY,QQQ
python -m scripts.trader capture
python -m scripts.trader review --context CONTEXT_UUID
```

Use the actual context ID from capture, not the placeholder. Preview makes no model
request. For a current broadly comparable universe, sync that universe too; a small
five-stock sync is only an integration test. Excluded/stale symbols remain disclosed.

Only when ready, while the input is still fresh:

```powershell
python -m scripts.trader review --context CONTEXT_UUID --send
python -m scripts.trader report
```

This sends market/news/account context to OpenAI and may be billable. Nothing
approves or places a trade. Paper submission is off by default. See README.md for
separate explicit paper commands, retained limits and unresolved execution risks.

Stop using older ZIP installation sequences. Keep the full original archive for
rollback/reference and use this package's manifest to review source changes.
