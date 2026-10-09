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


def has_live_quote(contract: dict[str, Any] | None) -> bool:
    """A listed contract with a symbol and a bid/ask or last. Missing fields are not filled in."""
    if not contract or not contract.get("symbol") or contract.get("strike") is None:
        return False
    return mid(contract) is not None


def _delta_distance(contract: dict[str, Any], side: str, delta_target: float) -> float | None:
    raw = contract.get("delta")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    delta = float(raw)
    if side == "call":
        return abs(delta - delta_target)
    return abs(delta + delta_target)


def _quoted_pool(contracts: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    return [c for c in contracts if c.get("side") == side and has_live_quote(c)]


def protective_wing(
    contracts: list[dict[str, Any]],
    side: str,
    strike: float,
    *,
    higher: bool,
    wide: bool = False,
) -> dict[str, Any] | None:
    """Next further strike that itself has a quote. An unquoted neighbor is not used."""
    quoted = _quoted_pool(contracts, side)
    if higher:
        return next_higher_strike(quoted, side, strike, wide=wide)
    return next_lower_strike(quoted, side, strike, wide=wide)


def best_quoted(
    contracts: list[dict[str, Any]],
    side: str,
    spot: float,
    delta_target: float,
) -> dict[str, Any] | None:
    """Closest quoted contract. A missing delta ranks by distance from spot, not list order."""
    higher = side == "call"

    def rank(contract: dict[str, Any]) -> tuple[float, ...]:
        strike = float(contract["strike"])
        distance = _delta_distance(contract, side, delta_target)
        otm = (strike - spot) if higher else (spot - strike)
        if distance is None:
            if otm > 0:
                return (1.0, otm, abs(strike - spot))
            return (2.0, abs(strike - spot), strike)
        return (0.0, distance, 0.0 if otm > 0 else 1.0, abs(otm))

    pool = _quoted_pool(contracts, side)
    if not pool:
        return None
    return sorted(pool, key=rank)[0]


def short_and_wing(
    contracts: list[dict[str, Any]],
    side: str,
    spot: float,
    delta_target: float,
    *,
    wide: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Inner strike plus a further out-of-the-money wing. Both must be quoted.

    A missing delta is not treated as zero, which would pin the short on the
    first listed strike and leave no wing. The nearest quoted short that has a
    further quoted wing is used instead. If no such pair is listed, return None.
    """
    higher = side == "call"
    pool = _quoted_pool(contracts, side)

    def rank(contract: dict[str, Any]) -> tuple[float, ...]:
        strike = float(contract["strike"])
        distance = _delta_distance(contract, side, delta_target)
        otm = (strike - spot) if side == "call" else (spot - strike)
        if distance is None:
            if otm > 0:
                return (1.0, otm, abs(strike - spot))
            return (2.0, abs(strike - spot), strike)
        return (0.0, distance, 0.0 if otm > 0 else 1.0, abs(otm))

    for short in sorted(pool, key=rank):
        wing = protective_wing(contracts, side, float(short["strike"]), higher=higher, wide=wide)
        if wing is None:
            continue
        if abs(float(wing["strike"]) - float(short["strike"])) < 0.01:
            continue
        return short, wing
    return None


def quoted_body_wings(
    contracts: list[dict[str, Any]],
    spot: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Same-strike short put and short call, each with a quoted wing."""
    puts = {round(float(c["strike"]), 4): c for c in _quoted_pool(contracts, "put")}
    calls = {round(float(c["strike"]), 4): c for c in _quoted_pool(contracts, "call")}
    shared = sorted(set(puts) & set(calls), key=lambda strike: (abs(strike - spot), strike))
    for strike in shared:
        lower = [key for key in puts if key < strike - 0.001]
        higher = [key for key in calls if key > strike + 0.001]
        if not lower or not higher:
            continue
        return puts[strike], calls[strike], puts[max(lower)], calls[min(higher)]
    return None


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
