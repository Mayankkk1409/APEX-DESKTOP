"""OHLC utilities and PatternSignal for the TA encyclopedia."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

PatternDirection = Literal["bullish", "bearish", "neutral"]
PatternStatus = Literal["forming", "confirmed", "invalidated"]
ReliabilityTier = Literal["high", "medium", "low"]

STRENGTH_EXPORT_FLOOR = 65
MAX_EXPORT_PATTERNS = 3


@dataclass(frozen=True)
class PatternSignal:
    id: str
    name: str
    family: str
    direction: PatternDirection
    status: PatternStatus
    strength: float
    reliability_tier: ReliabilityTier
    confirmation_evidence: tuple[str, ...] = ()
    invalidation: tuple[str, ...] = ()
    bar_index: int = -1
    invalidation_price: float | None = None
    timeframe: str = "daily"
    timestamp: str | None = None
    freshness: Literal["current", "stale"] = "current"

    def to_api_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["invalidation_price"] is None:
            del d["invalidation_price"]
        if d["timestamp"] is None:
            del d["timestamp"]
        return d


@dataclass
class OhlcWindow:
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]
    timestamps: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.closes)

    def bar(self, i: int) -> tuple[float, float, float, float]:
        return self.opens[i], self.highs[i], self.lows[i], self.closes[i]

    @classmethod
    def from_lists(
        cls,
        *,
        opens: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        volumes: Sequence[float],
        timestamps: Sequence[str] | None = None,
    ) -> OhlcWindow:
        return cls(
            opens=list(opens),
            highs=list(highs),
            lows=list(lows),
            closes=list(closes),
            volumes=list(volumes),
            timestamps=list(timestamps or []),
        )


def body(o: float, c: float) -> float:
    return abs(c - o)


def bar_range(h: float, l: float) -> float:
    return max(h - l, 1e-9)


def upper_wick(o: float, c: float, h: float) -> float:
    return h - max(o, c)


def lower_wick(o: float, c: float, l: float) -> float:
    return min(o, c) - l


def is_bullish(o: float, c: float) -> bool:
    return c > o


def is_bearish(o: float, c: float) -> bool:
    return c < o


def avg_body(w: OhlcWindow, i: int, look: int = 14) -> float:
    start = max(0, i - look)
    slice_ = range(start, i)
    if not slice_:
        o, _, _, c = w.bar(i)
        return body(o, c)
    total = 0.0
    for j in slice_:
        o, _, _, c = w.bar(j)
        total += body(o, c)
    return total / len(slice_)


def local_trend(w: OhlcWindow, i: int, look: int = 6) -> Literal["up", "down", "flat"]:
    j = max(0, i - look)
    a = w.closes[j]
    b = w.closes[max(0, i - 1)]
    pct = (b - a) / max(a, 1e-9)
    if pct > 0.012:
        return "up"
    if pct < -0.012:
        return "down"
    return "flat"


def swings(values: list[float], left: int = 3, right: int = 3, kind: str = "high") -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i in range(left, len(values) - right):
        v = values[i]
        ok = True
        for k in range(1, left + 1):
            ok = v >= values[i - k] if kind == "high" else v <= values[i - k]
            if not ok:
                break
        for k in range(1, right + 1):
            if not ok:
                break
            ok = v >= values[i + k] if kind == "high" else v <= values[i + k]
        if ok:
            out.append((i, v))
    return out


def vol_ratio(w: OhlcWindow, i: int, look: int = 20) -> float:
    if not w.volumes:
        return 1.0
    start = max(0, i - look + 1)
    avg = sum(w.volumes[start:i + 1]) / max(i - start + 1, 1)
    return w.volumes[i] / avg if avg else 1.0


def make_signal(
    *,
    pattern_id: str,
    name: str,
    family: str,
    direction: PatternDirection,
    status: PatternStatus,
    strength: float,
    reliability_tier: ReliabilityTier,
    confirmation_evidence: tuple[str, ...] = (),
    invalidation: tuple[str, ...] = (),
    bar_index: int = -1,
    invalidation_price: float | None = None,
    timeframe: str = "daily",
    timestamp: str | None = None,
) -> PatternSignal:
    return PatternSignal(
        id=pattern_id,
        name=name,
        family=family,
        direction=direction,
        status=status,
        strength=strength,
        reliability_tier=reliability_tier,
        confirmation_evidence=confirmation_evidence,
        invalidation=invalidation,
        bar_index=bar_index,
        invalidation_price=invalidation_price,
        timeframe=timeframe,
        timestamp=timestamp,
        freshness="current",
    )


def downweight_counter_trend(
    sig: PatternSignal,
    *,
    ema_bullish: bool,
    ema_bearish: bool,
    trend_direction: str,
) -> PatternSignal:
    """Down-weight counter-trend reversals against EMA stack."""
    counter = False
    if ema_bullish and sig.direction == "bearish":
        counter = True
    elif ema_bearish and sig.direction == "bullish":
        counter = True
    elif not ema_bullish and trend_direction == "bearish" and sig.direction == "bullish":
        counter = True
    elif not ema_bearish and trend_direction == "bullish" and sig.direction == "bearish":
        counter = True
    if not counter:
        return sig
    return PatternSignal(
        id=sig.id,
        name=sig.name,
        family=sig.family,
        direction=sig.direction,
        status="forming" if sig.status == "confirmed" else sig.status,
        strength=max(20.0, sig.strength * 0.55),
        reliability_tier="medium" if sig.reliability_tier == "high" else "low",
        confirmation_evidence=sig.confirmation_evidence,
        invalidation=sig.invalidation + ("Counter-trend vs EMA stack",),
        bar_index=sig.bar_index,
        invalidation_price=sig.invalidation_price,
        timeframe=sig.timeframe,
        timestamp=sig.timestamp,
        freshness=sig.freshness,
    )
