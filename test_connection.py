from alpaca.trading.client import (
    TradingClient,
)

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    PAPER_TRADING,
)


def main():

    client = TradingClient(
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
        paper=PAPER_TRADING,
    )

    account = client.get_account()

    print()
    print(
        "Connected to Alpaca "
        "Paper Trading"
    )
    print(
        "--------------------"
    )

    print(
        f"Status: "
        f"{account.status}"
    )

    print(
        f"Cash: "
        f"${float(account.cash):,.2f}"
    )

    print(
        f"Buying power: "
        f"${float(account.buying_power):,.2f}"
    )

    print(
        f"Portfolio value: "
        f"${float(account.portfolio_value):,.2f}"
    )


if __name__ == "__main__":
    main()