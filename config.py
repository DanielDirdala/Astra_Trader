import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


# ============================================================
# ALPACA
# ============================================================

ALPACA_API_KEY = os.getenv(
    "ALPACA_API_KEY",
    ""
).strip()

ALPACA_SECRET_KEY = os.getenv(
    "ALPACA_SECRET_KEY",
    ""
).strip()

PAPER_TRADING = True


# ============================================================
# DATABASE
# ============================================================

DB_HOST = os.getenv(
    "DB_HOST",
    "localhost"
).strip()

DB_PORT = int(
    os.getenv(
        "DB_PORT",
        "5432"
    )
)

DB_NAME = os.getenv(
    "DB_NAME",
    "astra_trader"
).strip()

DB_USER = os.getenv(
    "DB_USER",
    "postgres"
).strip()

DB_PASSWORD = os.getenv(
    "DB_PASSWORD",
    ""
)


# ============================================================
# ASTRA
# ============================================================

ASTRA_API_KEY = os.getenv(
    "ASTRA_API_KEY",
    ""
).strip()

ASTRA_API_URL = os.getenv(
    "ASTRA_API_URL",
    ""
).strip()

ASTRA_MODEL = os.getenv(
    "ASTRA_MODEL",
    ""
).strip()


# ============================================================
# DATA
# ============================================================

HISTORY_DAYS = 250

# Free Alpaca accounts will use IEX.
MARKET_DATA_FEED = "iex"


# ============================================================
# SCANNER
# ============================================================

SCANNER_TOP_N = 20

MIN_PRICE = 5.00

# Used only to prevent extremely illiquid securities
# from dominating the candidate pool.
MIN_AVG_VOLUME = 100_000


# ============================================================
# WEEKLY SELECTION
# ============================================================

WEEKLY_CANDIDATE_COUNT = 10


# ============================================================
# VALIDATION
# ============================================================

def validate_alpaca_config():

    if not ALPACA_API_KEY:
        raise RuntimeError(
            "ALPACA_API_KEY is missing."
        )

    if not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "ALPACA_SECRET_KEY is missing."
        )


def validate_database_config():

    if not DB_NAME:
        raise RuntimeError(
            "DB_NAME is missing."
        )

    if not DB_USER:
        raise RuntimeError(
            "DB_USER is missing."
        )