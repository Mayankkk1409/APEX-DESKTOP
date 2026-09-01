"""Technical analysis engine — 100-pattern encyclopedia and 10-layer composite score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.analysis.ta.detectors import detect_all_patterns, export_patterns, patterns_implemented_count
from app.analysis.ta.ohlc_utils import (
    MAX_EXPORT_PATTERNS,
    OhlcWindow,
    PatternSignal,
    STRENGTH_EXPORT_FLOOR,
)
from app.analysis.ta.pipeline import (
    TECH_LAYER_WEIGHTS,
    composite_technical_score,
    compute_layer_scores,
    professional_narrative,
    synthesize_direction,
)
from app.analysis.ta.pattern_catalog import PATTERN_CATALOG

__all__ = [
    "PatternSignal",
    "TechnicalAnalysisResult",
    "analyze_technicals",
    "patterns_implemented_count",
    "PATTERN_CATALOG",
    "TECH_LAYER_WEIGHTS",
]


@dataclass
class TechnicalAnalysisResult:
    score: float
    direction: Literal["bullish", "bearish", "neutral", "mixed"]
    patterns: list[PatternSignal] = field(default_factory=list)
    layer_scores: dict[str, float] = field(default_factory=dict)
    narrative: str = ""
    ema_aligned_bullish: bool = False
    ema_aligned_bearish: bool = False
    patterns_catalog_count: int = 100
    layer_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def confirmed_patterns(self) -> list[PatternSignal]:
        """Confirmed H/M tier patterns above strength floor."""
        return export_patterns(self.patterns, max_count=len(self.patterns))

    @property
    def chart_patterns(self) -> list[PatternSignal]:
        """Top confirmed patterns for chart highlights (max 3)."""
        return export_patterns(self.patterns, max_count=MAX_EXPORT_PATTERNS)

    def to_api_dict(self) -> dict[str, Any]:
        exported = [p.to_api_dict() for p in self.chart_patterns]
        return {
            "score": self.score,
            "direction": self.direction,
            "patterns": exported,
            "all_patterns_count": len(self.patterns),
            "catalog_patterns": self.patterns_catalog_count,
            "confirmed_count": len(self.confirmed_patterns),
            "layer_scores": self.layer_scores,
            "layer_weights": TECH_LAYER_WEIGHTS,
            "layer_breakdown": self.layer_breakdown,
            "narrative": self.narrative,
            "ema_aligned_bullish": self.ema_aligned_bullish,
            "ema_aligned_bearish": self.ema_aligned_bearish,
        }


def analyze_technicals(
    *,
    opens: list[float] | None = None,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    indicators: dict[str, Any],
    timestamps: list[str] | None = None,
    timeframe: str = "daily",
) -> TechnicalAnalysisResult:
    """Run full encyclopedia technical analysis on a captured OHLC window."""
    if opens is None:
        opens = [closes[0]] + closes[:-1]

    ema_bullish = bool(indicators.get("ema_aligned_bullish"))
    ema_bearish = bool(indicators.get("ema_aligned_bearish"))
    st = indicators.get("supertrend") or {}
    st_dir = st.get("direction", "neutral")
    trend_direction = "bullish" if st_dir == "bullish" else "bearish" if st_dir == "bearish" else "neutral"

    w = OhlcWindow.from_lists(
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        timestamps=timestamps,
    )

    patterns = detect_all_patterns(
        w,
        indicators,
        ema_bullish=ema_bullish,
        ema_bearish=ema_bearish,
        trend_direction=trend_direction,
        timeframe=timeframe,
    )

    layer_scores = compute_layer_scores(w, indicators, patterns)
    score = composite_technical_score(layer_scores)
    direction = synthesize_direction(layer_scores, patterns, indicators)
    narrative = professional_narrative(score, direction, patterns, layer_scores, indicators)

    layer_breakdown = {
        k: round(layer_scores.get(k, 50.0) * TECH_LAYER_WEIGHTS.get(k, 0.0), 2)
        for k in TECH_LAYER_WEIGHTS
    }

    return TechnicalAnalysisResult(
        score=score,
        direction=direction,
        patterns=patterns,
        layer_scores=layer_scores,
        layer_breakdown=layer_breakdown,
        narrative=narrative,
        ema_aligned_bullish=ema_bullish,
        ema_aligned_bearish=ema_bearish,
        patterns_catalog_count=patterns_implemented_count(),
    )
