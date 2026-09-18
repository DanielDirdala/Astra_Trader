"""Long-only PAPER equity P&L reconstruction, not broker/tax cost-basis reporting.

Reads all account activities from account creation, rather than summing SELL cash
or looking only at this week's buys. Unsupported activity makes the result
unavailable. FIFO is an explicit research convention, not Alpaca's tax method.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo
import re

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
ZERO = Decimal("0")


def decimal_number(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("A finite numeric value is required; missing is not zero.")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric value.") from exc
    if not result.is_finite():
        raise ValueError("NaN/infinite values are not allowed.")
    return result


def timestamp(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required.")
    return result.astimezone(UTC)


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def period_start(as_of: datetime, days: int) -> datetime:
    """Today plus the previous days-1 NY calendar dates, not a trading-day count."""
    if days not in (7, 14):
        raise ValueError("Choose a 7- or 14-calendar-day rolling reporting window.")
    local_date = timestamp(as_of).astimezone(NY).date() - timedelta(days=days - 1)
    return datetime.combine(local_date, time.min, NY).astimezone(UTC)


def activity_time(row: dict) -> datetime:
    value = row.get("transaction_time")
    if value:
        return timestamp(value)
    # Non-trade cash activities may have a date but no intraday timestamp.
    if row.get("date"):
        d = datetime.fromisoformat(str(row["date"])[:10]).date()
        return datetime.combine(d, time.min, NY).astimezone(UTC)
    raise ValueError("Activity has neither transaction_time nor date.")


def _equity_symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    if not symbol or "/" in symbol or re.fullmatch(r"[A-Z]{1,6}\d{6}[CP]\d{8}", symbol):
        raise ValueError("This FIFO ledger supports US stocks, not crypto or options.")
    return symbol


class PnLTracker:
    """The injected API must implement get(path, params, trading=True).

    Compatible with src.us_market_ops.AlpacaHTTP. All broker access is read-only.
    A separate paper account without transfers/corporate actions is simplest.
    """

    def __init__(self, api=None):
        self.api = api

    def fetch_activities(self, account_created_at: Any, as_of: datetime, max_pages: int = 500) -> list[dict]:
        if self.api is None:
            raise ValueError("An Alpaca read-only client is required.")
        start = timestamp(account_created_at)
        end = timestamp(as_of)
        if start > end:
            raise ValueError("Account creation date is in the future.")
        params = {"after": (start - timedelta(seconds=1)).isoformat(),
                  "until": end.isoformat(), "direction": "asc", "page_size": 100}
        rows: list[dict] = []
        pages_seen: set[str] = set()
        for _ in range(max_pages):
            page = self.api.get("/v2/account/activities", params, trading=True)
            if not isinstance(page, list):
                raise ValueError("Unexpected account activities response.")
            rows.extend(page)
            if len(page) < 100:
                return rows
            token = page[-1].get("id")
            if not token or token in pages_seen:
                raise ValueError("Activity pagination is incomplete or repeated.")
            pages_seen.add(token)
            params["page_token"] = token
        raise ValueError("Activity page budget reached; P&L is not certified complete.")

    @staticmethod
    def calculate(activities: list[dict], positions: list[dict], *, account_created_at: Any,
                  as_of: datetime, period_days: int = 14, history_complete: bool = False,
                  external_costs_usd: Any = None) -> dict:
        """External costs are a user-verified total for THIS window: API/data/etc.

        None means unknown, not free. Passing zero is an explicit assertion.
        Dividends, deposits, withdrawals, and interest are not trading profit.
        Current unrealized P&L is since entry, NOT unrealized change this period.
        """
        now = timestamp(as_of)
        start = period_start(now, period_days)
        problems: list[str] = []
        if not history_complete:
            problems.append("Full activity history was not verified.")
        try:
            created = timestamp(account_created_at)
            if created > now:
                raise ValueError("Account creation is later than the observation.")
        except (TypeError, ValueError):
            created = now
            problems.append("Account creation time is unavailable/invalid.")
        external = None
        if external_costs_usd is not None:
            external = decimal_number(external_costs_usd)
            if external < ZERO:
                raise ValueError("External period costs must be nonnegative.")

        lots: dict[str, deque] = defaultdict(deque)
        seen: dict[str, dict] = {}
        normalized = []
        for row in activities:
            identifier = row.get("id")
            if not identifier:
                problems.append("An activity has no stable ID.")
                continue
            if identifier in seen:
                if seen[identifier] != row:
                    problems.append("Conflicting versions of the same activity ID.")
                continue
            seen[identifier] = row
            try:
                occurred = activity_time(row)
                if occurred < created - timedelta(seconds=1):
                    problems.append("Activity precedes account creation; ledger origin is inconsistent.")
                elif occurred <= now:
                    normalized.append((occurred, str(identifier), row))
            except (ValueError, TypeError):
                problems.append("An activity has an invalid date.")
        normalized.sort(key=lambda item: (item[0], item[1]))
        # Equal-time fills of the same symbol may have an ambiguous FIFO order.
        ties: dict[tuple, int] = defaultdict(int)
        for occurred, _, row in normalized:
            if row.get("activity_type") == "FILL":
                ties[(occurred, row.get("symbol"))] += 1
        if any(count > 1 for count in ties.values()):
            problems.append("Same-symbol fills share an exact timestamp; FIFO order is ambiguous.")

        realized = ZERO
        losing_lot_pnl = ZERO
        fee_cash = ZERO
        fee_debits = ZERO
        excluded_income = ZERO
        cash_transfers = ZERO
        sells_in_period = 0
        fills_total = 0
        # Unknown events fail closed instead of guessing their effect on basis.
        ignored_cash = {"CSD", "CSW"}
        income = {"DIV", "DIVCGL", "DIVCGS", "INT"}
        broker_fees = {"FEE", "PTC", "PTR"}
        for occurred, _, row in normalized:
            in_period = start <= occurred <= now
            kind = str(row.get("activity_type", ""))
            try:
                if kind == "FILL":
                    if row.get("type", "fill") != "fill":
                        raise ValueError("Trade corrections require reconciliation.")
                    symbol = _equity_symbol(row.get("symbol"))
                    qty = decimal_number(row.get("qty"))
                    price = decimal_number(row.get("price"))
                    if qty <= ZERO or price <= ZERO:
                        raise ValueError("Invalid fill quantity or price.")
                    fills_total += 1
                    side = row.get("side")
                    if side == "buy":
                        lots[symbol].append([qty, price])
                    elif side == "sell":
                        if sum((lot[0] for lot in lots[symbol]), ZERO) < qty:
                            raise ValueError("Sell has missing opening lots or creates a short position.")
                        remaining = qty
                        while remaining > ZERO:
                            lot = lots[symbol][0]
                            matched = min(remaining, lot[0])
                            gain = (price - lot[1]) * matched
                            if in_period:
                                realized += gain
                                losing_lot_pnl += max(ZERO, -gain)
                            lot[0] -= matched
                            remaining -= matched
                            if lot[0] == ZERO:
                                lots[symbol].popleft()
                        if in_period:
                            sells_in_period += 1
                    else:
                        raise ValueError("Unsupported fill side.")
                elif kind in ignored_cash:
                    if in_period:
                        cash_transfers += decimal_number(row.get("net_amount"))
                elif kind in income:
                    if in_period:
                        excluded_income += decimal_number(row.get("net_amount"))
                elif kind in broker_fees:
                    if in_period:
                        amount = decimal_number(row.get("net_amount"))
                        fee_cash += amount
                        fee_debits += max(ZERO, -amount)
                else:
                    raise ValueError(f"Unsupported activity {kind!r}: transfers, splits and corrections need reconciliation.")
            except (ValueError, TypeError) as error:
                problems.append(str(error))

        current_qty: dict[str, Decimal] = {}
        unrealized = ZERO
        unrealized_losses = ZERO
        for position in positions:
            try:
                symbol = _equity_symbol(position.get("symbol"))
                if symbol in current_qty:
                    raise ValueError("Duplicate current position symbol.")
                qty = decimal_number(position.get("qty"))
                if position.get("side") != "long" or qty <= ZERO:
                    raise ValueError("Only long equity positions are supported.")
                if position.get("asset_class", "us_equity") != "us_equity":
                    raise ValueError("Non-equity position detected.")
                current_qty[symbol] = qty
                upl = decimal_number(position.get("unrealized_pl"))
                unrealized += upl
                unrealized_losses += max(ZERO, -upl)
            except (ValueError, TypeError) as error:
                problems.append(str(error))
        for symbol in set(current_qty) | set(lots):
            ledger_qty = sum((lot[0] for lot in lots[symbol]), ZERO)
            if abs(ledger_qty - current_qty.get(symbol, ZERO)) > Decimal("0.00000001"):
                problems.append(f"{symbol}: fill ledger does not reconcile to the captured position quantity.")

        complete = not problems
        trade_net = realized + fee_cash
        net_after_known_costs = trade_net - external if complete and external is not None else None
        return {
            "as_of": now.isoformat(), "period_start": start.isoformat(), "period_days": period_days,
            "window_definition": "today plus previous N-1 New York calendar dates",
            "method": "long-only FIFO research estimate; not tax/broker cost basis",
            "history_start": created.isoformat(), "complete": complete,
            "problems": sorted(set(problems)), "fills_examined": fills_total,
            "sell_fills_in_period": sells_in_period,
            "realized_gross_usd": money(realized) if complete else None,
            "broker_fee_cashflow_usd": money(fee_cash) if complete else None,
            "realized_after_broker_fees_usd": money(trade_net) if complete else None,
            "external_costs_usd": money(external) if external is not None else None,
            "net_realized_after_known_costs_usd": money(net_after_known_costs) if net_after_known_costs is not None else None,
            "current_unrealized_usd": money(unrealized) if complete else None,
            "current_unrealized_loss_usd": money(unrealized_losses) if complete else None,
            "gross_losing_lots_usd": money(losing_lot_pnl) if complete else None,
            "fee_debits_usd": money(fee_debits) if complete else None,
            "excluded_income_usd": money(excluded_income), "net_cash_transfers_usd": money(cash_transfers),
            "unrealized_note": "Current since-entry P&L; not profit realized or earned within this period.",
            "limitations": ["No tax/wash-sale accounting; unsupported events invalidate the estimate.",
                            "Position and activity endpoints are separate reads, not an atomic brokerage snapshot.",
                            "Current-period mark-to-market equity change is not reconstructed."]}
