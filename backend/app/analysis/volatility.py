"""Volatility math — HV, ranks, percentiles, expected move.

All functions are pure and evidence-backed. Missing history returns ``None`` rather
than inventing a number. Methodology is documented on each public helper.
"""

from __future__ import annotations

import math
from typing import Sequence

from app.analysis.score_bounds import assert_score_in_bounds


#: Common HV lookbacks in trading days (approx calendar windows labeled in the UI).
HV_WINDOWS: dict[str, int] = {
    "7D": 5,
    "14D": 10,
    "30D": 21,
    "60D": 42,
    "90D": 63,
    "6M": 126,
    "1Y": 252,
}

#: Minimum samples of the *same* windowed HV series required before rank/percentile
#: are reported. Fewer observations → unavailable (honest empty).
MIN_RANK_SAMPLES = 20


def log_returns(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a and a > 0 and b and b > 0:
            out.append(math.log(b / a))
    return out


def realized_vol(closes: Sequence[float], periods: int, *, annualize: float = 252.0) -> float | None:
    """Annualised historical volatility over the last ``periods`` closes.

    Uses sample standard deviation of log returns × √annualize. Returns ``None``
    when fewer than two valid returns exist inside the window.
    """
    if periods < 2 or len(closes) < 2:
        return None
    window = list(closes[-periods:])
    rets = log_returns(window)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var) * math.sqrt(annualize)


def rolling_hv(closes: Sequence[float], periods: int, *, annualize: float = 252.0) -> list[float | None]:
    """Rolling HV aligned to ``closes`` — ``None`` until the window is warm."""
    out: list[float | None] = [None] * len(closes)
    if periods < 2:
        return out
    for i in range(len(closes)):
        if i + 1 < periods:
            continue
        out[i] = realized_vol(closes[: i + 1], periods, annualize=annualize)
    return out


def percentile_rank(series: Sequence[float], value: float) -> float | None:
    """Percentile of ``value`` within ``series`` (0–100).

    Definition: share of historical observations **strictly below** the current
    value, plus half the ties — a standard empirical CDF percentile. Requires
    ``MIN_RANK_SAMPLES`` observations.
    """
    clean = [x for x in series if x is not None and math.isfinite(x)]
    if len(clean) < MIN_RANK_SAMPLES or not math.isfinite(value):
        return None
    below = sum(1 for x in clean if x < value)
    equal = sum(1 for x in clean if x == value)
    return 100.0 * (below + 0.5 * equal) / len(clean)


def range_rank(series: Sequence[float], value: float) -> float | None:
    """IV/HV Rank style 0–100 score: (value − min) / (max − min) × 100.

    Requires ``MIN_RANK_SAMPLES`` and a non-degenerate range. Flat history →
    unavailable rather than a fake 50.
    """
    clean = [x for x in series if x is not None and math.isfinite(x)]
    if len(clean) < MIN_RANK_SAMPLES or not math.isfinite(value):
        return None
    lo, hi = min(clean), max(clean)
    if hi <= lo:
        return None
    if value <= lo:
        return assert_score_in_bounds("range_rank", 0.0)
    if value >= hi:
        return assert_score_in_bounds("range_rank", 100.0)
    raw = 100.0 * (value - lo) / (hi - lo)
    return assert_score_in_bounds("range_rank", raw)


def expected_move(spot: float | None, iv: float | None, dte: int | None) -> dict[str, float | None]:
    """1σ expected move to expiry: spot × IV × √(DTE/365).

    Returns dollar and percent legs. Any missing input → all ``None``.
    """
    empty = {"dollars": None, "percent": None, "up": None, "down": None}
    if spot is None or iv is None or dte is None:
        return empty
    if spot <= 0 or iv < 0 or dte < 0:
        return empty
    years = dte / 365.0
    move = spot * iv * math.sqrt(years) if years > 0 else 0.0
    return {
        "dollars": move,
        "percent": (move / spot) * 100.0 if spot else None,
        "up": spot + move,
        "down": spot - move,
    }


def hv_snapshot(closes: Sequence[float]) -> dict[str, float | None]:
    """HV for every documented window that the close series can support."""
    out: dict[str, float | None] = {}
    for label, periods in HV_WINDOWS.items():
        out[label] = realized_vol(closes, periods) if len(closes) >= periods else None
    return out


def hv_rank_bundle(closes: Sequence[float], window_label: str = "30D") -> dict[str, float | None]:
    """HV, HV Rank, and HV Percentile for one window against its own rolling history."""
    periods = HV_WINDOWS.get(window_label, 21)
    current = realized_vol(closes, periods)
    series = [v for v in rolling_hv(closes, periods) if v is not None]
    return {
        "hv": current,
        "hv_rank": range_rank(series, current) if current is not None else None,
        "hv_percentile": percentile_rank(series, current) if current is not None else None,
        "history_points": float(len(series)),
    }


def iv_rank_from_history(iv_history: Sequence[float], current_iv: float | None) -> dict[str, float | None]:
    """True IV Rank / Percentile from a published IV history series.

    When history is too short or current IV is missing, every field is ``None``.
    Never invents a proxy from HV and labels it IV Rank.
    """
    if current_iv is None:
        return {"iv_rank": None, "iv_percentile": None, "history_points": 0.0}
    clean = [x for x in iv_history if x is not None and math.isfinite(x)]
    rank = range_rank(clean, current_iv)
    pct = percentile_rank(clean, current_iv)
    if pct is not None:
        pct = assert_score_in_bounds("iv_percentile", pct)
    return {
        "iv_rank": rank,
        "iv_percentile": pct,
        "history_points": float(len(clean)),
    }


def iv_rank_proxy(atm_iv: float | None, hv: float | None) -> float | None:
    """Documented IV/HV proxy when no IV history exists — always [0, 100] or None."""
    if atm_iv is None or not hv or hv <= 0:
        return None
    scaled = (float(atm_iv) / float(hv)) * 40.0
    bounded = min(100.0, max(0.0, scaled))
    return assert_score_in_bounds("iv_rank_proxy", round(bounded, 1))


def compute_iv_rank(
    iv_history: Sequence[float],
    current_iv: float | None,
    *,
    atm_iv: float | None = None,
    hv: float | None = None,
) -> dict[str, float | None]:
    """Single entry point for IV Rank — history-based first, proxy fallback, always bounded."""
    bundle = iv_rank_from_history(iv_history, current_iv)
    if bundle.get("iv_rank") is not None:
        return bundle
    proxy = iv_rank_proxy(current_iv if current_iv is not None else atm_iv, hv)
    return {
        "iv_rank": proxy,
        "iv_percentile": bundle.get("iv_percentile"),
        "history_points": bundle.get("history_points", 0.0),
        "proxy": 1.0 if proxy is not None else 0.0,
    }
