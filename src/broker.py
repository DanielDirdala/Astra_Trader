"""Legacy read-only account facade. Use paper tickets for every order submission."""
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY


class Broker:
    def __init__(self):
        self.client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

    def get_account(self):
        return self.client.get_account()

    def get_positions(self):
        return self.client.get_all_positions()

    def get_position(self, symbol):
        try:
            return self.client.get_open_position(symbol)
        except APIError as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise

    def get_clock(self):
        return self.client.get_clock()

    def submit_market_order(self, symbol, qty, side):
        raise RuntimeError("Legacy direct orders are disabled. Use scripts.trader paper prepare/submit.")

    def submit_limit_order(self, symbol, qty, side, limit_price):
        raise RuntimeError("Legacy direct orders are disabled. Use scripts.trader paper prepare/submit.")
