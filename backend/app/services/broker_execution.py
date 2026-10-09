"""Turn a broker acknowledgement into a fill, a partial, or a failure.

An explicit execution price is required before anything is marked filled.
The estimate is not a substitute. Paper, local simulation, and live stay labeled.
"""

from __future__ import annotations

from dataclasses import dataclass

_REJECTED = {"rejected", "canceled", "cancelled", "expired", "failed", "suspended", "error"}
_UNFILLED = {
    "accepted",
    "new",
    "pending_new",
    "accepted_for_bidding",
    "pending_cancel",
    "pending_replace",
    "pending_review",
}
_PARTIAL = {"partially_filled", "partial_fill", "partial"}
_FILLED = {"filled", "fill"}


@dataclass(frozen=True)
class Execution:
    outcome: str
    fill_price: float | None
    filled_qty: float | None
    broker_order_id: str | None
    venue: str
    reason: str | None


def _positive(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 0:
        return value
    return None


def _reason(broker: dict) -> str:
    reason = broker.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return "Broker rejected the order"


def _venue(broker: dict) -> str:
    named = broker.get("venue")
    if named in {"live", "paper", "simulation"}:
        return str(named)
    if broker.get("broker") == "demo_paper" or broker.get("session_paper_fill"):
        return "simulation"
    return "live"


def _broker_id(broker: dict) -> str | None:
    raw = broker.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def classify_execution(broker: object, *, requested_qty: float) -> Execution:
    if not isinstance(broker, dict):
        return Execution("ambiguous", None, None, None, "live", "Broker result was not an order")
    venue = _venue(broker)
    broker_id = _broker_id(broker)
    status = str(broker.get("status") or "").lower()
    price = _positive(broker.get("filled_avg_price"))
    filled_qty = _positive(broker.get("filled_qty"))

    if broker.get("rejected") is True or status in _REJECTED:
        return Execution("rejected", None, None, broker_id, venue, _reason(broker))

    if status in _PARTIAL:
        if price is None or filled_qty is None:
            return Execution("ambiguous", None, None, broker_id, venue, "Partial fill had no execution price")
        if filled_qty - requested_qty > 1e-9:
            return Execution("ambiguous", None, None, broker_id, venue, "Filled quantity exceeds the order")
        return Execution("partial", price, filled_qty, broker_id, venue, None)

    if status in _FILLED:
        if price is None:
            return Execution("ambiguous", None, None, broker_id, venue, "Filled status had no execution price")
        qty = filled_qty if filled_qty is not None else requested_qty
        if qty - requested_qty > 1e-9:
            return Execution("ambiguous", None, None, broker_id, venue, "Filled quantity exceeds the order")
        return Execution("filled", price, qty, broker_id, venue, None)

    if status in _UNFILLED:
        return Execution("accepted", None, None, broker_id, venue, None)

    if status == "" and price is not None:
        qty = filled_qty if filled_qty is not None else requested_qty
        return Execution("filled", price, qty, broker_id, venue, None)

    if status == "":
        return Execution("ambiguous", None, None, broker_id, venue, "Broker result had no status and no execution price")

    return Execution("ambiguous", None, None, broker_id, venue, f"Broker status {status} is not a fill")
