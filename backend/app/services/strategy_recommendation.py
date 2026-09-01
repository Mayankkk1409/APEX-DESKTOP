"""Deterministic strategy recommendation engine with staged gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.analysis.layers import (
    APEX_STRATEGY_NAME,
    EXECUTION_SCORE_BLOCKED_MAX,
    SCORE_TIER_CANDIDATE_MIN,
    SCORE_TIER_WATCHLIST_MAX,
)
from app.services.apex_strategy import ApexStrategyEligibility, ApexStrategyInput, check_apex_strategy_eligibility

NO_TRADE_LABEL = "No Trade / Insufficient Conviction"

# Strategies excluded from automated execution (undefined / unlimited risk)
UNDEFINED_RISK_STRATEGIES: frozenset[str] = frozenset(
    {
        "Naked Call",
        "Naked Put",
        "Short Strangle",
        "Short Straddle",
        "Ratio Spread",
        "Jade Lizard",
    }
)

DEFINED_RISK_PLAYBOOK: dict[str, dict[str, str]] = {
    "Short Iron Condor": {"bias": "neutral", "iv": "rich"},
    "Bull Call Spread": {"bias": "bullish", "iv": "cheap"},
    "Bear Put Spread": {"bias": "bearish", "iv": "cheap"},
    "Bull Put Spread (credit)": {"bias": "bullish", "iv": "rich"},
    "Bear Call Spread (credit)": {"bias": "bearish", "iv": "rich"},
    APEX_STRATEGY_NAME: {"bias": "neutral", "iv": "catalyst"},
    "APEX Benchmark Greeks Strategy": {"bias": "directional", "iv": "cheap"},
    "Married Put": {"bias": "bullish", "iv": "any"},
    "Married Call": {"bias": "bullish", "iv": "any"},  # legacy alias → APEX Benchmark Greeks Strategy
    "Diagonal Spread (bullish)": {"bias": "bullish", "iv": "fair"},
    "Diagonal Spread (bearish)": {"bias": "bearish", "iv": "fair"},
    "Calendar Spread": {"bias": "neutral", "iv": "fair"},
    "Long Straddle": {"bias": "neutral", "iv": "cheap"},
}


@dataclass
class MarketSnapshot:
    symbol: str
    spot: float | None
    direction: Literal["bullish", "bearish", "neutral"]
    data_fresh: bool = True
    spread_pct: float | None = None
    adv: float | None = None


@dataclass
class TechnicalAnalysisResultRef:
    score: float
    direction: str
    confirmed_pattern_count: int = 0


@dataclass
class PatternSignalRef:
    id: str
    name: str
    direction: str
    status: str
    strength: float


@dataclass
class StrategyCandidate:
    name: str
    score: float
    tier: str
    defined_risk: bool
    gate_notes: list[str] = field(default_factory=list)


@dataclass
class StrategyRecommendation:
    best_match: str
    tier: str
    score: float
    auto_exec_eligible: bool
    candidates: list[StrategyCandidate] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "best_match": self.best_match,
            "tier": self.tier,
            "score": self.score,
            "auto_exec_eligible": self.auto_exec_eligible,
            "candidates": [
                {
                    "name": c.name,
                    "score": c.score,
                    "tier": c.tier,
                    "defined_risk": c.defined_risk,
                    "gate_notes": c.gate_notes,
                }
                for c in self.candidates
            ],
            "rejection_reasons": self.rejection_reasons,
            "gates": self.gates,
        }


def _score_tier(score: float) -> str:
    if score <= EXECUTION_SCORE_BLOCKED_MAX:
        return "no_trade"
    if score <= SCORE_TIER_WATCHLIST_MAX:
        return "watchlist"
    return "candidate"


def _is_defined_risk(name: str) -> bool:
    return name not in UNDEFINED_RISK_STRATEGIES and "NO TRADE" not in name


def allows_auto_execution(
    strategy_name: str,
    *,
    execution_tier: str,
    composite: float,
    auto_exec_threshold: float = 85.0,
) -> bool:
    """Undefined-risk structures never auto-execute; tier encodes threshold band."""
    _ = composite, auto_exec_threshold
    if execution_tier != "auto_exec":
        return False
    if not _is_defined_risk(strategy_name):
        return False
    return True


def _rank_candidates(
    *,
    composite: float,
    direction: str,
    vol_signal: str,
    rsi: float,
    iv: float | None,
    hv: float | None,
    ivr: float | None,
    tech_score: float,
    sentiment_score: float | None,
    catalyst_active: bool,
    delta_theta_ratio: float | None,
    apex_eligible: bool,
    back_month_available: bool = False,
) -> list[StrategyCandidate]:
    """Rule-based candidate scoring — deterministic, not LLM."""
    candidates: list[StrategyCandidate] = []
    tier = _score_tier(composite)
    base_score = composite

    def add(name: str, bonus: float, notes: list[str]) -> None:
        if name in UNDEFINED_RISK_STRATEGIES:
            return
        candidates.append(
            StrategyCandidate(
                name=name,
                score=round(min(98.0, base_score + bonus), 1),
                tier=tier,
                defined_risk=_is_defined_risk(name),
                gate_notes=notes,
            )
        )

    iv_cheap = iv is not None and hv is not None and (hv - iv) > 0.10
    iv_rich = vol_signal == "sell_premium" or (iv is not None and hv is not None and (iv - hv) > 0.10)

    if apex_eligible and catalyst_active:
        add(APEX_STRATEGY_NAME, 12.0, ["APEX Strategy eligibility passed", "Catalyst window active"])

    if iv_cheap and tech_score > 80 and direction == "bullish":
        if delta_theta_ratio and delta_theta_ratio >= 10:
            add("APEX Benchmark Greeks Strategy", 8.0, ["Δ/Θ ratio ≥ 10", "IV cheap vs HV"])
        add("Bull Call Spread", 6.0, ["Bullish technical alignment", "IV cheap"])
    if iv_cheap and tech_score > 80 and direction == "bearish":
        add("Bear Put Spread", 6.0, ["Bearish technical alignment", "IV cheap"])
    if iv_cheap and direction == "neutral":
        add("Long Straddle", 4.0, ["Neutral direction", "IV cheap — long vol"])
    if iv_rich and 40 <= rsi <= 60:
        add("Short Iron Condor", 5.0, ["Range-bound RSI", "IV rich — premium selling"])
    if iv_rich and direction == "bullish":
        add("Bull Put Spread (credit)", 4.0, ["Mild bullish bias", "IV rich"])
    if iv_rich and direction == "bearish":
        add("Bear Call Spread (credit)", 4.0, ["Mild bearish bias", "IV rich"])
    if direction == "bullish" and sentiment_score and sentiment_score > 60:
        add("APEX Benchmark Greeks Strategy", 3.0, ["Sentiment supports bullish thesis"])
    if direction == "bullish":
        add("Married Put", 2.0, ["Protective hedge expression"])
    if back_month_available:
        if direction == "bullish":
            add("Diagonal Spread (bullish)", 2.0, ["Directional time spread"])
        if direction == "bearish":
            add("Diagonal Spread (bearish)", 2.0, ["Directional time spread"])
        add("Calendar Spread", 1.0, ["Neutral time-spread when back-month chain available"])

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def selection_rationale_for(
    strategy_name: str,
    *,
    direction: str,
    tech_score: float,
    vol_signal: str,
) -> str | None:
    """Explain when a neutral strategy is selected despite directional technical bias."""
    meta = DEFINED_RISK_PLAYBOOK.get(strategy_name, {})
    if meta.get("bias") != "neutral":
        return None
    if direction not in {"bullish", "bearish"}:
        return None
    return (
        f"Neutral {strategy_name} selected despite {direction} technical bias (score {tech_score:.1f}). "
        f"Volatility regime '{vol_signal}' overrides directional tilt — IV-rich premium-selling "
        "structures apply when RSI is range-bound per §9.1."
    )


def recommend_strategy(
    *,
    market: MarketSnapshot,
    technical: TechnicalAnalysisResultRef,
    composite: float,
    vol_signal: str,
    rsi: float | None = None,
    iv: float | None = None,
    hv: float | None = None,
    ivr: float | None = None,
    sentiment_score: float | None = None,
    catalyst_active: bool = False,
    catalyst_days: int | None = None,
    delta_theta_ratio: float | None = None,
    apex_input: ApexStrategyInput | None = None,
    auto_exec_threshold: float = 85.0,
    back_month_available: bool = False,
) -> StrategyRecommendation:
    """
    Staged gating: liquidity → defined-risk → data freshness → technical confirmation
    → IV regime → catalyst fit. Returns exactly one Best Match or No Trade.
    """
    rejection_reasons: list[str] = []
    gates: dict[str, bool] = {}

    # Gate 1: Data freshness
    gates["data_freshness"] = market.data_fresh
    if not market.data_fresh:
        rejection_reasons.append("Market data is stale")

    # Gate 2: Liquidity
    spread_ok = market.spread_pct is None or market.spread_pct <= 10.0
    adv_ok = market.adv is None or market.adv >= 1_000_000
    gates["liquidity"] = spread_ok and adv_ok
    if not spread_ok:
        rejection_reasons.append(f"Bid/ask spread too wide ({market.spread_pct:.1f}%)")
    if not adv_ok:
        rejection_reasons.append("ADV below liquidity minimum")

    # Gate 3: Composite tier
    tier = _score_tier(composite)
    gates["composite_tier"] = composite > EXECUTION_SCORE_BLOCKED_MAX
    if composite <= EXECUTION_SCORE_BLOCKED_MAX:
        return StrategyRecommendation(
            best_match=NO_TRADE_LABEL,
            tier="no_trade",
            score=composite,
            auto_exec_eligible=False,
            rejection_reasons=rejection_reasons + [f"Composite {composite} below {EXECUTION_SCORE_BLOCKED_MAX} no-trade tier"],
            gates=gates,
        )

    # Gate 4: IV crush block
    if iv and hv and iv > hv * 1.35:
        return StrategyRecommendation(
            best_match="NO TRADE — Wait for IV Crush",
            tier=tier,
            score=composite,
            auto_exec_eligible=False,
            rejection_reasons=rejection_reasons + ["IV exceeds HV by >35% — crush risk"],
            gates={**gates, "iv_regime": False},
        )
    gates["iv_regime"] = True

    # Gate 5: Technical confirmation
    gates["technical_confirmation"] = technical.score >= 55 or technical.confirmed_pattern_count > 0
    if not gates["technical_confirmation"]:
        rejection_reasons.append("Insufficient technical confirmation")

    # Gate 6: Catalyst / APEX Strategy
    apex_eligible = False
    if apex_input is not None:
        apex_result = check_apex_strategy_eligibility(apex_input)
        apex_eligible = apex_result.eligible
        gates["catalyst_fit"] = apex_eligible or not catalyst_active
        if catalyst_active and not apex_eligible:
            rejection_reasons.extend(apex_result.rejection_reasons)
    else:
        gates["catalyst_fit"] = True

    direction = market.direction
    rsi_v = rsi if rsi is not None else 50.0

    candidates = _rank_candidates(
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi_v,
        iv=iv,
        hv=hv,
        ivr=ivr,
        tech_score=technical.score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=delta_theta_ratio,
        apex_eligible=apex_eligible,
        back_month_available=back_month_available,
    )

    # Filter to defined-risk for primary selection when composite < candidate threshold
    viable = [c for c in candidates if c.defined_risk]
    if composite < SCORE_TIER_CANDIDATE_MIN:
        # Watchlist band — still pick best but mark not auto-exec
        best = viable[0] if viable else None
        if best is None:
            return StrategyRecommendation(
                best_match=NO_TRADE_LABEL,
                tier="watchlist",
                score=composite,
                auto_exec_eligible=False,
                candidates=candidates,
                rejection_reasons=rejection_reasons + [f"Composite {composite} in watchlist band ({EXECUTION_SCORE_BLOCKED_MAX + 1}–{SCORE_TIER_WATCHLIST_MAX})"],
                gates=gates,
            )
        return StrategyRecommendation(
            best_match=best.name,
            tier="watchlist",
            score=composite,
            auto_exec_eligible=False,
            candidates=candidates,
            rejection_reasons=rejection_reasons,
            gates=gates,
        )

    best = viable[0] if viable else None
    if best is None:
        return StrategyRecommendation(
            best_match=NO_TRADE_LABEL,
            tier="candidate",
            score=composite,
            auto_exec_eligible=False,
            candidates=candidates,
            rejection_reasons=rejection_reasons + ["No defined-risk strategy matched"],
            gates=gates,
        )

    auto_exec = (
        best.defined_risk
        and composite >= auto_exec_threshold
        and gates.get("liquidity", True)
        and gates.get("data_freshness", True)
        and gates.get("technical_confirmation", True)
    )

    return StrategyRecommendation(
        best_match=best.name,
        tier="candidate",
        score=composite,
        auto_exec_eligible=auto_exec,
        candidates=candidates,
        rejection_reasons=rejection_reasons,
        gates=gates,
    )
