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
    technical: float
    options_iv: float
    liquidity: float
    catalyst_fundamental: float
    payoff_risk: float
    cross_tf: float
    data_freshness: float
    penalties: dict[str, float] = field(default_factory=dict)
    raw_total: float = 0.0
    composite: float = 0.0
    tier: str = "no_trade"

    def to_api_dict(self) -> dict[str, Any]:
        weights = APEX_COMPOSITE_WEIGHTS
        components = [
            {
                "id": "technical",
                "label": "Technical",
                "score": self.technical,
                "weight": weights["technical"],
                "contribution": round(self.technical * weights["technical"], 1),
            },
            {
                "id": "options_iv",
                "label": "Options / IV",
                "score": self.options_iv,
                "weight": weights["options_iv"],
                "contribution": round(self.options_iv * weights["options_iv"], 1),
            },
            {
                "id": "liquidity",
                "label": "Liquidity",
                "score": self.liquidity,
                "weight": weights["liquidity"],
                "contribution": round(self.liquidity * weights["liquidity"], 1),
            },
            {
                "id": "catalyst_fundamental",
                "label": "Catalyst / Fundamental",
                "score": self.catalyst_fundamental,
                "weight": weights["catalyst_fundamental"],
                "contribution": round(self.catalyst_fundamental * weights["catalyst_fundamental"], 1),
            },
            {
                "id": "payoff_risk",
                "label": "Payoff / Risk",
                "score": self.payoff_risk,
                "weight": weights["payoff_risk"],
                "contribution": round(self.payoff_risk * weights["payoff_risk"], 1),
            },
            {
                "id": "cross_tf",
                "label": "Cross-TF",
                "score": self.cross_tf,
                "weight": weights["cross_tf"],
                "contribution": round(self.cross_tf * weights["cross_tf"], 1),
            },
            {
                "id": "data_freshness",
                "label": "Data Freshness",
                "score": self.data_freshness,
                "weight": weights["data_freshness"],
                "contribution": round(self.data_freshness * weights["data_freshness"], 1),
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


def compute_apex_composite_score(
    *,
    technical_score: float,
    options_iv_score: float,
    liquidity_score: float,
    catalyst_fundamental_score: float,
    payoff_risk_score: float,
    cross_tf_score: float,
    data_freshness_score: float,
    direction_conflict: bool = False,
    stale_data: bool = False,
    wide_spreads: bool = False,
) -> CompositeScoreBreakdown:
    """Compute weighted composite with documented penalties."""
    for name, val in (
        ("technical_score", technical_score),
        ("options_iv_score", options_iv_score),
        ("liquidity_score", liquidity_score),
        ("catalyst_fundamental_score", catalyst_fundamental_score),
        ("payoff_risk_score", payoff_risk_score),
        ("cross_tf_score", cross_tf_score),
        ("data_freshness_score", data_freshness_score),
    ):
        assert_score_in_bounds(name, val)
    weights = APEX_COMPOSITE_WEIGHTS
    raw = (
        technical_score * weights["technical"]
        + options_iv_score * weights["options_iv"]
        + liquidity_score * weights["liquidity"]
        + catalyst_fundamental_score * weights["catalyst_fundamental"]
        + payoff_risk_score * weights["payoff_risk"]
        + cross_tf_score * weights["cross_tf"]
        + data_freshness_score * weights["data_freshness"]
    )

    penalties: dict[str, float] = {}
    if direction_conflict:
        penalties["direction_conflict"] = 8.0
    if stale_data:
        penalties["stale_data"] = 6.0
    if wide_spreads:
        penalties["wide_spreads"] = 10.0

    composite = assert_score_in_bounds(
        "composite_score",
        round(max(0.0, min(100.0, raw - sum(penalties.values()))), 1),
    )

    return CompositeScoreBreakdown(
        technical=technical_score,
        options_iv=options_iv_score,
        liquidity=liquidity_score,
        catalyst_fundamental=catalyst_fundamental_score,
        payoff_risk=payoff_risk_score,
        cross_tf=cross_tf_score,
        data_freshness=data_freshness_score,
        penalties=penalties,
        raw_total=round(raw, 1),
        composite=composite,
        tier=_score_tier(composite),
    )
