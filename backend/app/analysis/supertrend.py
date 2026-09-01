from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SupertrendPoint:
    atr: float
    supertrend: float
    direction: int  # 1 bullish, -1 bearish


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def compute_supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr_length: int = 10,
    factor: float = 3.0,
) -> list[SupertrendPoint]:
    """ATR-length 10 / factor 3 SuperTrend from Full Document §4.5."""
    n = len(closes)
    if n == 0:
        return []
    trs: list[float] = []
    for i in range(n):
        prev_c = closes[i - 1] if i else closes[i]
        trs.append(true_range(highs[i], lows[i], prev_c))

    atrs: list[float] = []
    for i in range(n):
        if i < atr_length:
            atrs.append(sum(trs[: i + 1]) / (i + 1))
        else:
            atrs.append((atrs[-1] * (atr_length - 1) + trs[i]) / atr_length)

    points: list[SupertrendPoint] = []
    final_upper = 0.0
    final_lower = 0.0
    direction = 1
    st = closes[0]
    for i in range(n):
        mid = (highs[i] + lows[i]) / 2.0
        basic_upper = mid + factor * atrs[i]
        basic_lower = mid - factor * atrs[i]
        if i == 0:
            final_upper = basic_upper
            final_lower = basic_lower
        else:
            final_upper = basic_upper if basic_upper < final_upper or closes[i - 1] > final_upper else final_upper
            final_lower = basic_lower if basic_lower > final_lower or closes[i - 1] < final_lower else final_lower
        prev_dir = direction
        if closes[i] > final_upper:
            direction = 1
        elif closes[i] < final_lower:
            direction = -1
        else:
            direction = prev_dir
            if direction == 1 and final_lower < (points[-1].supertrend if points else final_lower):
                final_lower = points[-1].supertrend if points else final_lower
            if direction == -1 and final_upper > (points[-1].supertrend if points else final_upper):
                final_upper = points[-1].supertrend if points else final_upper
        st = final_lower if direction == 1 else final_upper
        points.append(SupertrendPoint(atr=atrs[i], supertrend=st, direction=direction))
    return points
