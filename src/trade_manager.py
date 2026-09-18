"""Retired mutable-approval executor. Kept to provide a clear migration error."""
class TradeManager:
    def __init__(self, broker=None, database=None):
        self.broker = broker
        self.db = database

    def execute_approved_trade(self, decision_id, quantity):
        raise RuntimeError("Legacy approval flags cannot authorize an order. Use scripts.trader paper prepare/submit.")
