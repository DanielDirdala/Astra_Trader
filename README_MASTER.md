# Astra Trader master-pipeline patch

This patch is additive to the consolidated v0.3 background/Flex build.
It does not touch `src/universe.py`, your ITOT cache, credentials, market database, or paper-order safeguards.

Changes:
- Adds `python -m scripts.trader master`.
- Keeps Python broad screening and Astra at up to three finalists.
- Removes rolling 7-day dollar/call/cooldown hard blocks.
- Keeps the per-request cost allowance, input/output limits, unknown-request blocking, background/resume protection, and usage logging.
- Never submits an Alpaca order from the master command.
- Completed Astra BUY proposals print entry/stop/target, risk/reward and the exact 1-share paper-ticket preparation command.
- If there is no BUY proposal, prints NO BUY SETUP THIS RUN and prepares nothing.

Usage:

    python -m scripts.trader master

Local pipeline preview only (no Astra generation).

    python -m scripts.trader master --skip-sync --send-astra

Uses the already-synced daily cache, captures fresh live/news/account context, and makes one deliberate Astra finalist request.

Paper order remains separate:

    python -m scripts.trader paper prepare --review REVIEW_UUID --symbol SYMBOL --qty 1
    python -m scripts.trader paper submit TICKET_UUID --ack-earnings-unknown

The submission command retains the existing exact typed approval requirement.
