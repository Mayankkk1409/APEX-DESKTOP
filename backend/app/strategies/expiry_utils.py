"""Expiration calendar helpers for multi-expiration strategies."""

from __future__ import annotations

from datetime import date


def next_expiry_after(expiration_dates: list[str], front_expiry: str) -> str | None:
    """Return the first listed expiration strictly after ``front_expiry``."""
    try:
        front = date.fromisoformat(front_expiry)
    except (TypeError, ValueError):
        return None
    parsed: list[date] = []
    for raw in expiration_dates:
        try:
            parsed.append(date.fromisoformat(raw))
        except (TypeError, ValueError):
            continue
    future = sorted(d for d in parsed if d > front)
    return future[0].isoformat() if future else None


def nearest_expiry_in_window(
    expiration_dates: list[str],
    *,
    low: int,
    high: int,
    today: date | None = None,
) -> str | None:
    """Listed expiry whose DTE is inside [low, high], nearest the window midpoint."""
    ref = today or date.today()
    midpoint = (int(low) + int(high)) / 2.0
    best: tuple[float, str] | None = None
    for raw in expiration_dates:
        try:
            parsed = date.fromisoformat(str(raw)[:10])
        except (TypeError, ValueError):
            continue
        dte = (parsed - ref).days
        if dte < int(low) or dte > int(high):
            continue
        distance = abs(dte - midpoint)
        if best is None or distance < best[0]:
            best = (distance, parsed.isoformat())
    return None if best is None else best[1]


def days_between(start: str, end: str, *, today: date | None = None) -> int | None:
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    if today is not None:
        return max((d1 - today).days, 0)
    return max((d1 - d0).days, 0)
