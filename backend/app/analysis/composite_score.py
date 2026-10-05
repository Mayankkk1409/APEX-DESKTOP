"""APEX Composite Score — weighted pillars with explainable breakdown and penalties."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analysis.layers import (
    APEX_COMPOSITE_WEIGHTS,
    COMPOSITE_THRESHOLD_FULL_DOC,
    COMPOSITE_THRESHOLD_PROJECT,
    DEFAULT_AUTO_EXEC_THRESHOLD,
    SCORE_TIER_CANDIDATE_MIN,
    SCORE_TIER_NO_TRADE_MAX,
    SCORE_TIER_WATCHLIST_MAX,
)
from app.analysis.score_bounds import assert_score_in_bounds


@dataclass
class CompositeScoreBreakdown:
    technicals: float
    volatility: float
    options: float
    sentiment: float | None
    fundamentals: float
    weights_applied: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)
    raw_total: float = 0.0
    composite: float = 0.0
    tier: str = "no_trade"

    def to_api_dict(self) -> dict[str, Any]:
        weights = self.weights_applied or APEX_COMPOSITE_WEIGHTS
        sent = self.sentiment
        components = [
            {
                "id": "technicals",
                "label": "Technicals",
                "score": self.technicals,
                "weight": weights["technicals"],
                "contribution": round(self.technicals * weights["technicals"], 1),
            },
            {
                "id": "volatility",
                "label": "Volatility",
                "score": self.volatility,
                "weight": weights["volatility"],
                "contribution": round(self.volatility * weights["volatility"], 1),
            },
            {
                "id": "options",
                "label": "Greeks quality",
                "score": self.options,
                "weight": weights["options"],
                "contribution": round(self.options * weights["options"], 1),
            },
            {
                "id": "sentiment",
                "label": "Sentiment",
                "score": sent,
                "weight": weights.get("sentiment", 0.0),
                "contribution": round(sent * weights["sentiment"], 1) if sent is not None else 0.0,
            },
            {
                "id": "fundamentals",
                "label": "Fundamentals",
                "score": self.fundamentals,
                "weight": weights["fundamentals"],
                "contribution": round(self.fundamentals * weights["fundamentals"], 1),
            },
        ]
        return {
            "composite": self.composite,
            "raw_total": self.raw_total,
            "tier": self.tier,
            "thresholds": {
                "no_trade_max": SCORE_TIER_NO_TRADE_MAX,
                "watchlist_max": SCORE_TIER_WATCHLIST_MAX,
                "candidate_min": SCORE_TIER_CANDIDATE_MIN,
                "full_doc": COMPOSITE_THRESHOLD_FULL_DOC,
                "auto_exec_default": DEFAULT_AUTO_EXEC_THRESHOLD,
                "project_apex": COMPOSITE_THRESHOLD_PROJECT,
            },
            "weights": weights,
            "components": components,
            "penalties": self.penalties,
        }


def _score_tier(composite: float) -> str:
    if composite <= SCORE_TIER_NO_TRADE_MAX:
        return "no_trade"
    if composite <= SCORE_TIER_WATCHLIST_MAX:
        return "watchlist"
    return "candidate"


def _weights_for_sentiment(sentiment_score: float | None) -> dict[str, float]:
    """Documented §8.1 weights. Missing sentiment is omitted and the rest are renormalized."""
    documented = APEX_COMPOSITE_WEIGHTS
    if sentiment_score is not None:
        return dict(documented)
    active = ("technicals", "volatility", "options", "fundamentals")
    total = sum(documented[key] for key in active)
    applied = {key: documented[key] / total for key in active}
    applied["sentiment"] = 0.0
    applied["risk"] = 0.0
    return applied


def compute_apex_composite_score(
    *,
    technical_score: float,
    volatility_score: float,
    options_score: float,
    sentiment_score: float | None,
    fundamental_score: float,
    direction_conflict: bool = False,
    stale_data: bool = False,
    wide_spreads: bool = False,
    earnings_before_expiry: bool = False,
) -> CompositeScoreBreakdown:
    """Full Document §8.1: 30/25/20/15/10, then documented penalties. Risk weight is 0.

    A missing sentiment score is omitted. It is not replaced with a neutral 50.
    """
    for name, val in (
        ("technical_score", technical_score),
        ("volatility_score", volatility_score),
        ("options_score", options_score),
        ("sentiment_score", sentiment_score),
        ("fundamental_score", fundamental_score),
    ):
        if val is not None:
            assert_score_in_bounds(name, val)
    weights = _weights_for_sentiment(sentiment_score)
    raw = (
        technical_score * weights["technicals"]
        + volatility_score * weights["volatility"]
        + options_score * weights["options"]
        + (sentiment_score or 0.0) * weights["sentiment"]
        + fundamental_score * weights["fundamentals"]
    )

    penalties: dict[str, float] = {}
    if direction_conflict:
        penalties["direction_conflict"] = 8.0
    if stale_data:
        penalties["stale_data"] = 6.0
    if wide_spreads:
        penalties["wide_spreads"] = 10.0
    if earnings_before_expiry:
        penalties["earnings_before_expiry"] = 4.0

    composite = assert_score_in_bounds(
        "composite_score",
        round(max(0.0, min(100.0, raw - sum(penalties.values()))), 1),
    )

    return CompositeScoreBreakdown(
        technicals=technical_score,
        volatility=volatility_score,
        options=options_score,
        sentiment=sentiment_score,
        fundamentals=fundamental_score,
        weights_applied=weights,
        penalties=penalties,
        raw_total=round(raw, 1),
        composite=composite,
        tier=_score_tier(composite),
    )
