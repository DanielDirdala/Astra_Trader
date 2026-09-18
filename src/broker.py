from alpaca.trading.client import (
    TradingClient,
)

from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
)

from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
)

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    PAPER_TRADING,
)


class Broker:

    def __init__(self):

        self.client = TradingClient(
            ALPACA_API_KEY,
            ALPACA_SECRET_KEY,
            paper=PAPER_TRADING,
        )

    def get_account(self):

        return self.client.get_account()

    def get_positions(self):

        return (
            self.client
            .get_all_positions()
        )

    def get_position(
        self,
        symbol,
    ):

        try:

            return (
                self.client
                .get_open_position(
                    symbol
                )
            )

        except Exception:

            return None

    def get_clock(self):

        return (
            self.client
            .get_clock()
        )

    def submit_market_order(
        self,
        symbol,
        qty,
        side,
    ):

        order_side = (
            OrderSide.BUY
            if side.upper() == "BUY"
            else OrderSide.SELL
        )

        request = (
            MarketOrderRequest(
                symbol=
                    symbol.upper(),

                qty=
                    qty,

                side=
                    order_side,

                time_in_force=
                    TimeInForce.DAY,
            )
        )

        return (
            self.client
            .submit_order(
                order_data=request
            )
        )

    def submit_limit_order(
        self,
        symbol,
        qty,
        side,
        limit_price,
    ):

        order_side = (
            OrderSide.BUY
            if side.upper() == "BUY"
            else OrderSide.SELL
        )

        request = (
            LimitOrderRequest(
                symbol=
                    symbol.upper(),

                qty=
                    qty,

                side=
                    order_side,

                limit_price=
                    round(
                        float(
                            limit_price
                        ),
                        2
                    ),

                time_in_force=
                    TimeInForce.GTC,
            )
        )

        return (
            self.client
            .submit_order(
                order_data=request
            )
        )