"""Stock leg sizing for strategies that buy, sell, or short the underlying.

Share count is contracts times the chain multiplier. Shares already held cover a
new short call only when they are not already covering another short call.
A missing locate feed is not treated as a shortable confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from app.services.occ_symbol import parse_occ
from app.strategies.payoffs.core import covered_call_payoff, protective_put_payoff
from app.strategies.registry import StrategySpec, get_strategy_spec

_CENT = Decimal("0.01")
# No broker locate file is available. This exact sentence is the infeasible reason.
SHORT_STOCK_INFEASIBLE = "cannot confirm easy-to-borrow / margin"


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def multiplier_from_contracts(
    contracts: list[dict[str, Any]] | None,
    *,
    explicit: int | None = None,
) -> int:
    """Use the multiplier the chain publishes. 100 is used only when that is the published value or the chain omits it."""
    published: list[int] = []
    for contract in contracts or []:
        if not isinstance(contract, dict):
            continue
        raw = contract.get("multiplier")
        if raw is None:
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0:
            published.append(number)
    if published:
        return published[0]
    if explicit is not None and int(explicit) > 0:
        return int(explicit)
    return 100


def required_shares(contracts: int | float | Decimal, multiplier: int) -> int:
    count = (Decimal(str(contracts)) * Decimal(int(multiplier))).to_integral_value(rounding=ROUND_HALF_UP)
    shares = int(count)
    if shares <= 0:
        raise ValueError("Share quantity must be positive")
    return shares


@dataclass(frozen=True)
class Holdings:
    shares_long: int = 0
    avg_cost: Decimal | None = None
    shares_encumbered: int = 0
    shares_short: int = 0

    @property
    def unencumbered_long(self) -> int:
        return max(int(self.shares_long) - int(self.shares_encumbered), 0)


def read_holdings(positions: list[Any], ticker: str) -> Holdings:
    """Long shares, average cost, shares already covering a short call, and existing short stock."""
    root = ticker.upper()
    long_qty = 0
    short_qty = 0
    avg: Decimal | None = None
    encumbered = 0
    for pos in positions:
        symbol = str(getattr(pos, "symbol", "") or "").upper()
        asset = str(getattr(pos, "asset_class", "") or "")
        qty = getattr(pos, "qty", 0) or 0
        try:
            qty_dec = Decimal(str(qty))
        except Exception:
            continue
        if asset != "us_option" and symbol == root:
            whole = int(qty_dec.to_integral_value(rounding=ROUND_HALF_UP))
            if whole > 0:
                long_qty += whole
                raw_avg = getattr(pos, "avg_cost", None)
                if raw_avg is not None:
                    avg = money(raw_avg)
            elif whole < 0:
                short_qty += abs(whole)
            continue
        if asset == "us_option" and qty_dec < 0:
            parsed = parse_occ(symbol)
            if parsed is None or parsed.root != root or parsed.right != "C":
                continue
            mult = int(getattr(pos, "multiplier", 0) or 0)
            if mult <= 1:
                mult = 100
            encumbered += int(abs(qty_dec) * Decimal(mult))
    return Holdings(
        shares_long=long_qty,
        avg_cost=avg,
        shares_encumbered=encumbered,
        shares_short=short_qty,
    )


@dataclass(frozen=True)
class StockPlan:
    side: Literal["buy", "sell"]
    position_intent: str
    shares_required: int
    order_qty: int
    shares_used: int
    entry: Decimal | None
    entry_source: str
    cost_basis: Decimal | None
    note: str
    short_unconfirmed: bool
    covered_by_holdings: bool

    def order_leg(self, ticker: str) -> dict[str, Any] | None:
        if self.order_qty <= 0:
            return None
        return {
            "symbol": ticker.upper(),
            "side": self.side,
            "qty": self.order_qty,
            "asset_class": "us_equity",
            "position_intent": self.position_intent,
        }


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"${money(value):.2f}"


def plan_stock(
    *,
    equity_side: Literal["buy", "sell"],
    contracts: int | float | Decimal,
    multiplier: int,
    holdings: Holdings,
    ask: Decimal | float | None = None,
    reference_price: Decimal | float | None = None,
) -> StockPlan:
    """Decide whether to buy, sell short, or use shares the account already holds."""
    required = required_shares(contracts, multiplier)
    ask_dec = money(ask) if ask is not None else None
    ref_dec = money(reference_price) if reference_price is not None else None

    if equity_side == "sell":
        # The ledger is not a locate. Do not submit a short, and do not drop the leg.
        entry = ref_dec
        source = "scan reference price" if entry is not None else "unavailable"
        return StockPlan(
            side="sell",
            position_intent="infeasible",
            shares_required=required,
            order_qty=0,
            shares_used=0,
            entry=entry,
            entry_source=source,
            cost_basis=None,
            note=SHORT_STOCK_INFEASIBLE,
            short_unconfirmed=True,
            covered_by_holdings=False,
        )

    free = holdings.unencumbered_long
    used = min(free, required)
    order_qty = required - used
    basis = holdings.avg_cost if used else None
    if order_qty == 0:
        entry = basis
        source = "position average cost" if entry is not None else "cost basis unknown"
    elif used == 0:
        if ask_dec is not None:
            entry = ask_dec
            source = "live ask"
        elif ref_dec is not None:
            entry = ref_dec
            source = "scan reference price; live ask was not on the quote"
        else:
            entry = None
            source = "live ask unavailable"
    else:
        if basis is not None and ask_dec is not None:
            entry = money((Decimal(used) * basis + Decimal(order_qty) * ask_dec) / Decimal(required))
            source = "average of position cost and live ask"
        elif ask_dec is not None:
            entry = ask_dec
            source = "live ask for the shares being bought; held-share cost basis is unknown"
        elif basis is not None and ref_dec is not None:
            entry = money((Decimal(used) * basis + Decimal(order_qty) * ref_dec) / Decimal(required))
            source = "average of position cost and scan reference price; live ask was not on the quote"
        else:
            entry = basis or ref_dec
            source = "partial holdings; live ask was not on the quote"

    if order_qty == 0:
        basis_txt = (
            f" Cost basis {_fmt(basis)}."
            if basis is not None
            else " Cost basis is not on the position."
        )
        note = (
            f"Uses {used} of your {holdings.shares_long} shares. "
            f"Using {used} shares already held.{basis_txt} No additional shares are bought."
        )
    elif used:
        basis_txt = f" at cost basis {_fmt(basis)}" if basis is not None else ""
        note = (
            f"Uses {used} of your {holdings.shares_long} shares. "
            f"Buying {order_qty} shares to cover the shortfall{basis_txt}."
        )
    else:
        ask_txt = f" at the live ask {_fmt(ask_dec)}" if ask_dec is not None else ""
        if ask_dec is None:
            ask_txt = ". Live ask was not on the quote"
        note = f"Buying {order_qty} shares{ask_txt}."
    if holdings.shares_encumbered and free < holdings.shares_long:
        note += f" {holdings.shares_encumbered} shares already cover another short call and are not reused."

    return StockPlan(
        side="buy",
        position_intent="buy" if order_qty else "use_existing",
        shares_required=required,
        order_qty=order_qty,
        shares_used=used,
        entry=entry,
        entry_source=source,
        cost_basis=basis,
        note=note,
        short_unconfirmed=False,
        covered_by_holdings=order_qty == 0 and used > 0,
    )


def _option(legs: list[dict[str, Any]], *, side: str, action: str) -> dict[str, Any] | None:
    for leg in legs:
        if leg.get("side") == side and str(leg.get("action") or "").lower() == action:
            return leg
    return None


def _apply_payoff(spec: StrategySpec, metrics: dict[str, Any], plan: StockPlan) -> None:
    if plan.entry is None:
        return
    legs = metrics.get("legs") or []
    shares = plan.shares_required
    if spec.payoff_function_ref == "payoff_covered_call":
        call = _option(legs, side="call", action="sell")
        if not call or call.get("strike") is None:
            return
        payoff = covered_call_payoff(
            stock_cost=plan.entry,
            call_strike=call.get("strike"),
            call_premium=call.get("mid") or 0,
            shares=shares,
        )
        metrics.update(payoff)
        return
    if spec.payoff_function_ref == "payoff_protective_put":
        put = _option(legs, side="put", action="buy")
        if not put or put.get("strike") is None:
            return
        payoff = protective_put_payoff(
            stock_cost=plan.entry,
            put_strike=put.get("strike"),
            put_premium=put.get("mid") or 0,
            shares=shares,
        )
        metrics.update(payoff)


def apply_equity_holdings(
    spec: StrategySpec | None,
    metrics: dict[str, Any],
    *,
    ticker: str,
    spot: float | None,
    multiplier: int,
    shares_held: int = 0,
    shares_encumbered: int = 0,
    shares_short: int = 0,
    avg_cost: Decimal | float | None = None,
    ask: Decimal | float | None = None,
    contracts: int | float = 1,
) -> dict[str, Any]:
    """Attach order quantity and the holdings note. Does not invent a locate."""
    if spec is None or not spec.equity_required or spec.equity_leg_spec is None:
        return metrics
    if metrics.get("validation_blocked"):
        return metrics
    side = spec.equity_leg_spec.side
    holdings = Holdings(
        shares_long=max(int(shares_held or 0), 0),
        avg_cost=money(avg_cost) if avg_cost is not None else None,
        shares_encumbered=max(int(shares_encumbered or 0), 0),
        shares_short=max(int(shares_short or 0), 0),
    )
    plan = plan_stock(
        equity_side=side,
        contracts=contracts,
        multiplier=multiplier,
        holdings=holdings,
        ask=ask,
        reference_price=spot,
    )
    legs = [dict(leg) for leg in (metrics.get("legs") or []) if isinstance(leg, dict)]
    stock_legs = [leg for leg in legs if leg.get("side") == "stock"]
    if not stock_legs:
        stock_legs = [
            {
                "action": "sell" if side == "sell" else "buy",
                "side": "stock",
                "strike": spot,
                "expiry": None,
                "mid": float(plan.entry) if plan.entry is not None else spot,
                "symbol": ticker,
                "quantity": plan.shares_required,
            }
        ]
        legs = stock_legs + [leg for leg in legs if leg.get("side") != "stock"]
    for leg in stock_legs:
        leg["symbol"] = leg.get("symbol") or ticker
        leg["quantity"] = plan.shares_required
        leg["order_qty"] = plan.order_qty
        leg["shares_used"] = plan.shares_used
        leg["shares_held"] = holdings.shares_long
        leg["already_held"] = plan.order_qty == 0 and plan.shares_used > 0
        leg["position_intent"] = plan.position_intent
        leg["action"] = "sell" if side == "sell" and plan.order_qty else leg.get("action") or ("sell" if side == "sell" else "buy")
        if plan.order_qty == 0 and side == "buy":
            leg["action"] = "buy"
        if plan.entry is not None and plan.order_qty:
            leg["mid"] = float(plan.entry)
        if plan.short_unconfirmed:
            leg["short_unconfirmed"] = True
            leg["order_qty"] = 0
            leg["action"] = "sell"
    metrics = dict(metrics)
    metrics["legs"] = legs
    metrics["equity_note"] = plan.note
    if plan.short_unconfirmed:
        metrics["validation_blocked"] = True
        metrics["validation_error"] = SHORT_STOCK_INFEASIBLE
    metrics["equity_order_qty"] = plan.order_qty
    metrics["equity_shares_used"] = plan.shares_used
    metrics["equity_covered_by_holdings"] = plan.covered_by_holdings
    metrics["per_contract_multiplier"] = multiplier
    metrics["stock_entry"] = float(plan.entry) if plan.entry is not None else None
    metrics["stock_entry_source"] = plan.entry_source
    _apply_payoff(spec, metrics, plan)
    return metrics


@dataclass(frozen=True)
class SubmissionEquity:
    order_legs: list[dict[str, Any]]
    covered_by_holdings: bool
    note: str
    short_unconfirmed: bool


def submission_equity(
    *,
    strategy_name: str | None,
    ticker: str,
    contracts: int | float,
    multiplier: int,
    positions: list[Any],
    ask: float | None = None,
    reference_price: float | None = None,
) -> SubmissionEquity:
    spec = get_strategy_spec(strategy_name or "")
    if spec is None or not spec.equity_required or spec.equity_leg_spec is None:
        return SubmissionEquity([], False, "", False)
    holdings = read_holdings(positions, ticker)
    plan = plan_stock(
        equity_side=spec.equity_leg_spec.side,
        contracts=contracts,
        multiplier=multiplier,
        holdings=holdings,
        ask=ask,
        reference_price=reference_price,
    )
    if plan.short_unconfirmed:
        return SubmissionEquity([], False, SHORT_STOCK_INFEASIBLE, True)
    leg = plan.order_leg(ticker)
    return SubmissionEquity(
        [leg] if leg else [],
        plan.covered_by_holdings,
        plan.note,
        False,
    )


def leg_completeness_error(strategy_name: str | None, legs: list[Any]) -> str | None:
    """Fail when the built legs do not match the registry template count."""
    spec = get_strategy_spec(strategy_name or "")
    if spec is None or spec.leg_count <= 0 or not spec.tradeable:
        return None
    count = sum(1 for leg in legs if isinstance(leg, dict) and leg.get("side"))
    if count == spec.leg_count:
        return None
    return f"Leg count {count} does not match the {spec.display_name} template ({spec.leg_count})."


def is_short_call(leg: dict[str, Any]) -> bool:
    """A short call on the option ticket. A stock sell is not a short call."""
    action = str(leg.get("action") or leg.get("side") or "").lower()
    option_side = str(leg.get("option_side") or "").lower()
    metric_side = str(leg.get("side") or "").lower()
    if option_side == "call" and action == "sell":
        return True
    if metric_side == "call" and str(leg.get("action") or "").lower() == "sell":
        return True
    return False


def is_short_option(leg: dict[str, Any]) -> bool:
    """A short call or short put. A stock sell is not an option short."""
    action = str(leg.get("action") or leg.get("side") or "").lower()
    if action != "sell":
        return False
    option_side = str(leg.get("option_side") or "").lower()
    metric_side = str(leg.get("side") or "").lower()
    return option_side in {"call", "put"} or metric_side in {"call", "put"}


def partition_option_legs(legs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Buys first. Short calls and short puts wait until every buy has filled."""
    buys: list[dict[str, Any]] = []
    shorts: list[dict[str, Any]] = []
    for leg in legs:
        if is_short_option(leg):
            shorts.append(leg)
        else:
            buys.append(leg)
    return buys, shorts


def build_order_ticket(
    metrics: dict[str, Any],
    *,
    tradeable: bool,
    equity_required: bool,
    ticker: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Order rows for a complete, tradeable structure. An infeasible short is not included."""
    if not tradeable:
        return [], []
    strategy_legs: list[dict[str, Any]] = []
    equity_legs: list[dict[str, Any]] = []
    for leg in metrics.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        if leg.get("side") == "stock":
            if not equity_required or leg.get("short_unconfirmed"):
                continue
            order_qty = leg.get("order_qty")
            if order_qty is None:
                order_qty = leg.get("quantity") or 0
            try:
                order_qty = int(order_qty)
            except (TypeError, ValueError):
                order_qty = 0
            if order_qty <= 0:
                continue
            intent = str(leg.get("position_intent") or leg.get("action") or "").lower()
            if intent in {"sell_short", "infeasible"}:
                continue
            equity_legs.append(
                {
                    "symbol": leg.get("symbol") or ticker.upper(),
                    "side": "sell" if intent == "sell" else "buy",
                    "qty": order_qty,
                    "asset_class": "us_equity",
                    "position_intent": leg.get("position_intent") or leg.get("action") or "buy",
                    "order_type": "market",
                    "price": leg.get("mid"),
                }
            )
            continue
        occ = leg.get("symbol")
        action = str(leg.get("action") or "").lower()
        if not occ or action not in {"buy", "sell"}:
            continue
        order_type = str(leg.get("order_type") or "market")
        limit_price = leg.get("limit_price")
        strategy_legs.append(
            {
                "symbol": occ,
                "side": action,
                "qty": leg.get("quantity") or 1,
                "strike": leg.get("strike"),
                "option_side": leg.get("side"),
                "expiry": leg.get("expiry"),
                "asset_class": "us_option",
                "order_type": order_type,
                "price": leg.get("mid") if leg.get("mid") is not None else limit_price,
                "limit_price": limit_price if order_type == "limit" else None,
                "limit_basis": leg.get("limit_basis") if order_type == "limit" else None,
                "quote_as_of": leg.get("quote_as_of"),
                "quoted_side": leg.get("quoted_side"),
            }
        )
    return strategy_legs, equity_legs
