from src.database import Database


class ApprovalManager:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

    def pending(
        self,
    ):

        return (
            self.db
            .get_pending_decisions()
        )

    def approve(
        self,
        decision_id,
        quantity=None,
        notes=None,
    ):

        self.db.approve_trade(
            decision_id,
            quantity,
            notes,
        )

    def reject(
        self,
        decision_id,
        notes=None,
    ):

        self.db.reject_trade(
            decision_id,
            notes,
        )