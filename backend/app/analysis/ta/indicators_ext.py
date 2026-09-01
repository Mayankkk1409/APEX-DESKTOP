"""Extended indicator series for TA pattern detection."""

from __future__ import annotations

import math
from typing import Sequence

from app.analysis.indicators import ema, sma
from app.analysis.supertrend import true_range


def atr_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float]:
    trs: list[float] = []
    for i in range(len(closes)):
        prev_c = closes[i - 1] if i else closes[i]
        trs.append(true_range(highs[i], lows[i], prev_c))
    atrs: list[float] = []
    for i in range(len(trs)):
        if i < period:
            atrs.append(sum(trs[: i + 1]) / (i + 1))
        else:
            atrs.append((atrs[-1] * (period - 1) + trs[i]) / period)
    return atrs


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> dict[str, list[float]]:
    k: list[float] = []
    for i in range(len(closes)):
        start = max(0, i - k_period + 1)
        hh = max(highs[start : i + 1])
        ll = min(lows[start : i + 1])
        if hh == ll:
            k.append(50.0)
        else:
            k.append(100.0 * (closes[i] - ll) / (hh - ll))
    d = sma(k, d_period)
    return {"k": k, "d": d}


def cci(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
) -> list[float]:
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    out: list[float] = []
    for i in range(len(tp)):
        start = max(0, i - period + 1)
        window = tp[start : i + 1]
        mean = sum(window) / len(window)
        md = sum(abs(x - mean) for x in window) / len(window)
        if md == 0:
            out.append(0.0)
        else:
            out.append((tp[i] - mean) / (0.015 * md))
    return out


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out.append(out[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            out.append(out[-1] - volumes[i])
        else:
            out.append(out[-1])
    return out


def vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> list[float]:
    out: list[float] = []
    cum_vol = 0.0
    cum_pv = 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3.0
        cum_vol += v
        cum_pv += tp * v
        out.append(cum_pv / cum_vol if cum_vol else c)
    return out


def keltner(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
    mult: float = 1.5,
) -> dict[str, list[float]]:
    mid = ema(closes, period)
    atr = atr_series(highs, lows, closes, period)
    upper = [m + mult * a for m, a in zip(mid, atr)]
    lower = [m - mult * a for m, a in zip(mid, atr)]
    return {"mid": mid, "upper": upper, "lower": lower}


def percent_b(closes: Sequence[float], upper: Sequence[float], lower: Sequence[float]) -> list[float]:
    out: list[float] = []
    for c, u, l in zip(closes, upper, lower):
        width = u - l
        out.append((c - l) / width if width else 0.5)
    return out


def find_cross(a: Sequence[float], b: Sequence[float], from_idx: int = 0) -> tuple[int, bool] | None:
    for i in range(len(a) - 1, max(from_idx, 1), -1):
        if not all(math.isfinite(x) for x in (a[i], b[i], a[i - 1], b[i - 1])):
            continue
        prev = a[i - 1] - b[i - 1]
        cur = a[i] - b[i]
        if prev <= 0 < cur:
            return i, True
        if prev >= 0 > cur:
            return i, False
    return None


def divergence(
    price: Sequence[float],
    indicator: Sequence[float],
    look: int = 20,
    kind: str = "bullish",
) -> bool:
    if len(price) < look + 2:
        return False
    p_win = price[-look:]
    i_win = indicator[-look:]
    if kind == "bullish":
        p_low_i = min(range(len(p_win)), key=lambda j: p_win[j])
        p_prev_low = min(p_win[: max(1, p_low_i)])
        i_at_low = i_win[p_low_i]
        i_prev = i_win[0]
        return p_win[p_low_i] < p_prev_low and i_at_low > i_prev
    p_high_i = max(range(len(p_win)), key=lambda j: p_win[j])
    p_prev_high = max(p_win[: max(1, p_high_i)])
    i_at_high = i_win[p_high_i]
    i_prev = i_win[0]
    return p_win[p_high_i] > p_prev_high and i_at_high < i_prev
