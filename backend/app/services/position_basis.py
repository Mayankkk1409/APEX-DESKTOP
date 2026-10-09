"""Remaining average cost after a fill.

Increase blends size. A partial close or short buyback keeps the open basis.
A full close removes the lot. Crossing through zero opens the remainder at the fill.
"""

from __future__ import annotations


def position_after_fill(
    qty: float,
    avg: float,
    *,
    side: str,
    fill_qty: float,
    fill_px: float,
) -> tuple[float, float] | None:
    """Return ``(new_qty, new_avg)``, or ``None`` when the lot is flat."""
    if fill_qty <= 0:
        raise ValueError("fill_qty must be positive")
    if fill_px <= 0:
        raise ValueError("fill_px must be positive")
    signed = fill_qty if side == "buy" else -fill_qty
    new_qty = qty + signed
    if abs(new_qty) < 1e-9:
        return None
    increasing = qty == 0 or (qty > 0 and signed > 0) or (qty < 0 and signed < 0)
    if increasing:
        new_avg = (abs(qty) * avg + abs(signed) * fill_px) / abs(new_qty)
        return new_qty, new_avg
    if (qty > 0 and new_qty > 0) or (qty < 0 and new_qty < 0):
        return new_qty, avg
    return new_qty, fill_px
