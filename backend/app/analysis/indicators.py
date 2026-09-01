from __future__ import annotations

import math
from typing import Sequence

from app.analysis.layers import (
    BOLLINGER_PERIOD,
    BOLLINGER_STD,
    EMA_PERIODS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
)
from app.analysis.supertrend import compute_supertrend


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def sma(values: Sequence[float], period: int) -> list[float]:
    out: list[float] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        denom = period if i >= period - 1 else i + 1
        out.append(running / denom)
    return out


def rsi(closes: Sequence[float], period: int = RSI_PERIOD) -> list[float]:
    if len(closes) < 2:
        return [50.0] * len(closes)
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_g = sum(gains[1 : period + 1]) / period if len(gains) > period else sum(gains) / max(len(gains) - 1, 1)
    avg_l = sum(losses[1 : period + 1]) / period if len(losses) > period else sum(losses) / max(len(losses) - 1, 1)
    out = [50.0]
    for i in range(1, len(closes)):
        if i >= period:
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
        rs = avg_g / avg_l if avg_l else 100.0
        out.append(100 - (100 / (1 + rs)))
    return out


def macd(closes: Sequence[float]) -> dict:
    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)
    line = [f - s for f, s in zip(fast, slow)]
    signal = ema(line, MACD_SIGNAL)
    hist = [l - s for l, s in zip(line, signal)]
    return {"line": line, "signal": signal, "histogram": hist}


def bollinger(closes: Sequence[float], period: int = BOLLINGER_PERIOD, stdev: float = BOLLINGER_STD) -> dict:
    mid = sma(closes, period)
    upper: list[float] = []
    lower: list[float] = []
    width: list[float] = []
    for i, m in enumerate(mid):
        window = closes[max(0, i - period + 1) : i + 1]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        sd = math.sqrt(var)
        u = m + stdev * sd
        l = m - stdev * sd
        upper.append(u)
        lower.append(l)
        width.append((u - l) / m if m else 0.0)
    return {"mid": mid, "upper": upper, "lower": lower, "width": width}


def pivot_points(high: float, low: float, close: float) -> dict:
    """Full Document §4.7 / Project APEX §4 standard formula, extended to R5/S5."""
    pp = (high + low + close) / 3.0
    return {
        "pp": pp,
        "r1": (pp * 2) - low,
        "r2": pp + (high - low),
        "r3": high + 2 * (pp - low),
        "r4": high + 3 * (pp - low),
        "r5": high + 4 * (pp - low),
        "s1": (pp * 2) - high,
        "s2": pp - (high - low),
        "s3": low - 2 * (high - pp),
        "s4": low - 3 * (high - pp),
        "s5": low - 4 * (high - pp),
    }


def stdev(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def historical_vol(closes: Sequence[float], periods: int = 20) -> float:
    if len(closes) < 2:
        return 0.0
    window = closes[-periods:]
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window)) if window[i - 1]]
    return stdev(rets) * math.sqrt(252)


def last_ema_stack(closes: Sequence[float]) -> dict[int, float]:
    return {p: ema(closes, p)[-1] for p in EMA_PERIODS}


def compute_all(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> dict:
    st = compute_supertrend(highs, lows, closes)
    m = macd(closes)
    r = rsi(closes)
    bb = bollinger(closes)
    stack = last_ema_stack(closes)
    aligned_bull = list(stack.values()) == sorted(stack.values(), reverse=True)
    aligned_bear = list(stack.values()) == sorted(stack.values())
    return {
        "ema": stack,
        "ema_aligned_bullish": aligned_bull,
        "ema_aligned_bearish": aligned_bear and not aligned_bull,
        "macd": {"line": m["line"][-1], "signal": m["signal"][-1], "histogram": m["histogram"][-1]},
        "rsi": r[-1],
        "bollinger": {
            "mid": bb["mid"][-1],
            "upper": bb["upper"][-1],
            "lower": bb["lower"][-1],
            "width": bb["width"][-1],
        },
        "bollinger_series": bb,
        "macd_series": m,
        "rsi_series": r,
        "supertrend": {
            "value": st[-1].supertrend if st else closes[-1],
            "direction": "bullish" if st and st[-1].direction == 1 else "bearish",
            "atr": st[-1].atr if st else 0.0,
        },
        "supertrend_series": st,
        "volume": {
            "last": volumes[-1] if volumes else 0.0,
            "avg": (sum(volumes[-20:]) / min(len(volumes), 20)) if volumes else 0.0,
        },
        "series": {"macd": m, "rsi": r, "bollinger": bb, "supertrend": [p.__dict__ for p in st]},
    }
