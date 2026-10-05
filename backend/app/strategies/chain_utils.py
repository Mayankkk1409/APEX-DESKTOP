"""Chain snapshot utilities for strategy leg building."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

Side = Literal["call", "put"]


def mid(contract: dict[str, Any] | None) -> float | None:
    if not contract:
        return None
    bid, ask = contract.get("bid"), contract.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    last = contract.get("last")
    return float(last) if last is not None else None


def pick_strike(
    contracts: list[dict[str, Any]], side: Side, spot: float, delta_target: float
) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike")]
    if not pool:
        return None
    if side == "call":
        pool.sort(key=lambda c: abs((c.get("delta") or 0) - delta_target))
    else:
        pool.sort(key=lambda c: abs((c.get("delta") or 0) + delta_target))
    return pool[0]


def resolve_contract_from_recommended(
    contracts: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
    side: Side,
    spot: float,
    *,
    delta_target: float = 0.55,
) -> dict[str, Any] | None:
    """Single source of truth: recommended anchor contract, then delta/strike fallback."""
    if recommended and recommended.get("side") == side and recommended.get("strike") is not None:
        match = contract_at_strike(contracts, side, float(recommended["strike"]))
        if match:
            return match
        contract_id = recommended.get("contract_id") or recommended.get("symbol")
        if contract_id:
            by_id = next((c for c in contracts if c.get("symbol") == contract_id), None)
            if by_id and by_id.get("side") == side:
                return by_id
    return pick_strike(contracts, side, spot, delta_target) or nearest_strike_contract(contracts, side, spot)


def contract_at_strike(contracts: list[dict[str, Any]], side: str, strike: float) -> dict[str, Any] | None:
    return next(
        (
            c
            for c in contracts
            if c.get("side") == side and c.get("strike") is not None and abs(float(c["strike"]) - strike) < 0.01
        ),
        None,
    )


def nearest_strike_contract(contracts: list[dict[str, Any]], side: str, spot: float) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike")]
    if not pool:
        return None
    return min(pool, key=lambda c: abs(float(c["strike"]) - spot))


def next_higher_strike(contracts: list[dict[str, Any]], side: str, strike: float, *, wide: bool = False) -> dict[str, Any] | None:
    pool = sorted(
        [c for c in contracts if c.get("side") == side and c.get("strike", 0) > strike],
        key=lambda c: c["strike"],
    )
    if not pool:
        return None
    idx = 1 if wide and len(pool) > 1 else 0
    return pool[min(idx, len(pool) - 1)]


def next_lower_strike(contracts: list[dict[str, Any]], side: str, strike: float, *, wide: bool = False) -> dict[str, Any] | None:
    pool = sorted(
        [c for c in contracts if c.get("side") == side and c.get("strike", 0) < strike],
        key=lambda c: c["strike"],
        reverse=True,
    )
    if not pool:
        return None
    idx = 1 if wide and len(pool) > 1 else 0
    return pool[min(idx, len(pool) - 1)]


def sorted_strikes(contracts: list[dict[str, Any]], side: str) -> list[float]:
    return sorted({float(c["strike"]) for c in contracts if c.get("side") == side and c.get("strike") is not None})


def dte_from_expiry(expiry: str | None, *, today: date | None = None) -> int | None:
    if not expiry:
        return None
    try:
        exp = date.fromisoformat(expiry)
    except (TypeError, ValueError):
        return None
    ref = today or datetime.now(timezone.utc).date()
    return max((exp - ref).days, 0)


def make_option_leg(
    action: str,
    contract: dict[str, Any] | None,
    *,
    expiry: str | None = None,
    quantity: int = 1,
) -> dict[str, Any] | None:
    if not contract:
        return None
    m = mid(contract)
    if m is not None:
        m = round(float(m), 2)
    return {
        "action": action,
        "side": contract.get("side"),
        "strike": contract.get("strike"),
        "expiry": expiry or contract.get("expiry"),
        "mid": m,
        "symbol": contract.get("symbol"),
        "quantity": quantity,
    }


def make_stock_leg(action: str, spot: float, ticker: str, *, quantity: int = 100) -> dict[str, Any]:
    shares = int(quantity) if int(quantity) > 0 else 100
    return {
        "action": action,
        "side": "stock",
        "strike": spot,
        "expiry": None,
        "mid": spot,
        "symbol": ticker,
        "quantity": shares,
        "order_qty": shares,
    }


def net_debit_credit(legs: list[dict[str, Any]]) -> tuple[float, str]:
    debits = sum((l.get("mid") or 0) * (l.get("quantity") or 1) for l in legs if l.get("action") == "buy")
    credits = sum((l.get("mid") or 0) * (l.get("quantity") or 1) for l in legs if l.get("action") == "sell")
    net = debits - credits
    return round(net, 4), "debit" if net >= 0 else "credit"


def normalize_leg_mids(legs: list[dict[str, Any]], *, precision: int = 2) -> list[dict[str, Any]]:
    """Round leg mids to display precision so payoff math matches the trade card."""
    for leg in legs:
        mid_val = leg.get("mid")
        if mid_val is not None:
            leg["mid"] = round(float(mid_val), precision)
    return legs


def net_credit_per_share(legs: list[dict[str, Any]]) -> float:
    """Signed net per share: positive = credit received, negative = debit paid."""
    net, _ = net_debit_credit(legs)
    return round(-net, 4)
