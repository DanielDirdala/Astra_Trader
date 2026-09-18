from src.database import Database


def main():

    db = Database()

    decisions = (
        db.get_pending_decisions()
    )

    if not decisions:

        print(
            "No pending Astra trades."
        )

        return

    for trade in decisions:

        print()
        print(
            "=" * 50
        )

        print(
            f"Decision ID: "
            f"{trade['id']}"
        )

        print(
            f"Symbol: "
            f"{trade['symbol']}"
        )

        print(
            f"Action: "
            f"{trade['action']}"
        )

        print(
            f"Confidence: "
            f"{trade['confidence']}"
        )

        print(
            f"Entry: "
            f"{trade['entry_price']}"
        )

        print(
            f"Stop: "
            f"{trade['stop_price']}"
        )

        print(
            f"Target: "
            f"{trade['target_price']}"
        )

        print()
        print(
            trade["thesis"]
            or ""
        )


if __name__ == "__main__":
    main()