from src.broker import Broker
from src.database import Database


class TradeManager:

    def __init__(
        self,
        broker=None,
        database=None,
    ):

        self.broker = (
            broker
            or Broker()
        )

        self.db = (
            database
            or Database()
        )

    def execute_approved_trade(
        self,
        decision_id,
        quantity,
    ):

        decision = (
            self.db
            .get_decision(
                decision_id
            )
        )

        if decision is None:

            raise ValueError(
                "Decision not found."
            )

        if (
            decision["status"]
            != "APPROVED"
        ):

            raise RuntimeError(
                "Trade has not been approved."
            )

        action = (
            decision[
                "action"
            ]
        )

        if action not in (
            "BUY",
            "SELL",
        ):

            raise RuntimeError(
                f"{action} is not an "
                f"executable order action."
            )

        return (
            self.broker
            .submit_market_order(
                symbol=
                    decision[
                        "symbol"
                    ],

                qty=
                    quantity,

                side=
                    action,
            )
        )