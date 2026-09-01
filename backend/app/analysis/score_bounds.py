"""Hard bounds for 0–100 scores surfaced on trade cards and scan layers."""

from __future__ import annotations

import math


class ScoreOutOfBoundsError(ValueError):
    """Raised when a score leaves the documented 0–100 range."""


def assert_score_bounded(name: str, value: float | int | None) -> float | None:
    """Return ``value`` when inside [0, 100]; raise otherwise (never silently clamp)."""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ScoreOutOfBoundsError(f"{name} must be a finite number, got {value!r}")
    fv = float(value)
    if fv < 0.0 or fv > 100.0:
        raise ScoreOutOfBoundsError(f"{name} out of bounds [0, 100]: {fv}")
    return fv


def assert_score_in_bounds(name: str, value: float | int | None) -> float | None:
    """Alias for ``assert_score_bounded`` — hard-fail at computation time."""
    return assert_score_bounded(name, value)


def validate_scan_scores(
    *,
    iv_rank: float | int | None = None,
    iv_percentile: float | int | None = None,
    composite: float | int | None = None,
    technical: float | int | None = None,
    sentiment: float | int | None = None,
    fundamentals: float | int | None = None,
    hv_rank: float | int | None = None,
) -> None:
    """Validate all documented 0–100 scan scores; hard-fail on any violation."""
    checks = {
        "iv_rank": iv_rank,
        "iv_percentile": iv_percentile,
        "composite_score": composite,
        "technical_score": technical,
        "sentiment_score": sentiment,
        "fundamentals_score": fundamentals,
        "hv_rank": hv_rank,
    }
    for name, val in checks.items():
        if val is not None:
            assert_score_bounded(name, val)
