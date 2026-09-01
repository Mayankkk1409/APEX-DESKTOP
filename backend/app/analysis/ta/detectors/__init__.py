"""Orchestrates all 100-pattern detectors."""

from __future__ import annotations

from typing import Any

from app.analysis.ta.detectors.candlesticks import detect_candlestick_patterns
from app.analysis.ta.detectors.charts import detect_chart_patterns
from app.analysis.ta.detectors.indicators import detect_indicator_patterns
from app.analysis.ta.detectors.levels_gaps import detect_levels_gaps_harmonic
from app.analysis.ta.ohlc_utils import OhlcWindow, PatternSignal, downweight_counter_trend
from app.analysis.ta.pattern_catalog import PATTERN_CATALOG, PATTERN_BY_ID


def detect_all_patterns(
    w: OhlcWindow,
    indicators: dict[str, Any],
    *,
    ema_bullish: bool,
    ema_bearish: bool,
    trend_direction: str,
    timeframe: str = "daily",
) -> list[PatternSignal]:
    """Run all encyclopedia pattern detectors and apply EMA counter-trend filters."""
    raw: list[PatternSignal] = []
    raw.extend(detect_candlestick_patterns(w))
    raw.extend(detect_chart_patterns(w))
    raw.extend(detect_indicator_patterns(w, indicators))
    raw.extend(detect_levels_gaps_harmonic(w, indicators))

    catalog_ids = {p.id for p in PATTERN_CATALOG}
    filtered: list[PatternSignal] = []
    for sig in raw:
        if sig.id not in catalog_ids:
            continue
        sig = PatternSignal(
            id=sig.id,
            name=sig.name,
            family=sig.family,
            direction=sig.direction,
            status=sig.status,
            strength=sig.strength,
            reliability_tier=sig.reliability_tier,
            confirmation_evidence=sig.confirmation_evidence,
            invalidation=sig.invalidation,
            bar_index=sig.bar_index,
            invalidation_price=sig.invalidation_price,
            timeframe=timeframe,
            timestamp=sig.timestamp,
            freshness=sig.freshness,
        )
        sig = downweight_counter_trend(
            sig, ema_bullish=ema_bullish, ema_bearish=ema_bearish, trend_direction=trend_direction
        )
        if sig.status != "invalidated":
            filtered.append(sig)

    return _dedupe_strongest(filtered)


def _dedupe_strongest(patterns: list[PatternSignal]) -> list[PatternSignal]:
    best: dict[str, PatternSignal] = {}
    for p in patterns:
        prev = best.get(p.id)
        if prev is None or p.strength > prev.strength:
            best[p.id] = p
    return list(best.values())


def export_patterns(patterns: list[PatternSignal], *, max_count: int = 3) -> list[PatternSignal]:
    """Only confirmed H/M tier patterns above strength floor, max N for chart."""
    eligible = [
        p
        for p in patterns
        if p.status == "confirmed"
        and p.reliability_tier in ("high", "medium")
        and p.strength >= 65
    ]
    eligible.sort(key=lambda p: p.strength, reverse=True)
    return eligible[:max_count]


def patterns_implemented_count() -> int:
    return len(PATTERN_CATALOG)


def catalog_coverage() -> dict[str, int]:
    from collections import Counter
    detected_families = Counter(p.family for p in PATTERN_CATALOG)
    return dict(detected_families)
