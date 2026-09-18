CORE_UNIVERSE = [

    # Technology
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AVGO",
    "ORCL",
    "CRM",
    "ADBE",
    "INTC",
    "QCOM",

    # Internet / communications
    "GOOGL",
    "META",
    "NFLX",

    # Consumer
    "AMZN",
    "TSLA",
    "WMT",
    "COST",
    "HD",
    "LOW",
    "NKE",
    "SBUX",

    # Financial
    "JPM",
    "BAC",
    "GS",
    "MS",
    "V",
    "MA",

    # Healthcare
    "LLY",
    "UNH",
    "JNJ",
    "ABBV",
    "MRK",

    # Industrial / aerospace
    "CAT",
    "GE",
    "RTX",
    "BA",
    "LMT",

    # Energy
    "XOM",
    "CVX",

    # Semiconductors
    "MU",
    "AMAT",
    "LRCX",
    "KLAC",

    # ETFs / context
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
]


BENCHMARKS = [
    "SPY",
    "QQQ",
]


def get_universe():

    return sorted(
        set(
            CORE_UNIVERSE
        )
    )


def get_stock_universe():

    return [
        symbol
        for symbol
        in get_universe()
        if symbol not in BENCHMARKS
    ]