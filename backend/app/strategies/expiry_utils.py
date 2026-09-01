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


def days_between(start: str, end: str, *, today: date | None = None) -> int | None:
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    if today is not None:
        return max((d1 - today).days, 0)
    return max((d1 - d0).days, 0)
