from __future__ import annotations

from typing import Literal


def estimate_order_cost(
    qty: float,
    price: float,
    *,
    asset_class: Literal["us_equity", "us_option", "us_index"] = "us_equity",
    multiplier: int | None = None,
) -> float:
    """Estimated cash impact. Equity = qty * price. Options = qty * 100 * premium."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    if price < 0:
        raise ValueError("price must be non-negative")
    if asset_class == "us_option":
        mult = multiplier if multiplier is not None else 100
        return round(qty * mult * price, 2)
    return round(qty * price, 2)


def account_impact(side: str, estimated_cost: float) -> float:
    if side == "buy":
        return -abs(estimated_cost)
    if side == "sell":
        return abs(estimated_cost)
    raise ValueError("side must be buy or sell")
