"""Deterministic strategy recommendation engine with staged gating."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from app.analysis.layers import (
    APEX_STRATEGY_NAME,
    EXECUTION_SCORE_BLOCKED_MAX,
    SCORE_TIER_WATCHLIST_MAX,
)
from app.services.apex_strategy import ApexStrategyEligibility, ApexStrategyInput, check_apex_strategy_eligibility
from app.strategies.registry import STRATEGY_REGISTRY, StrategySpec, get_strategy_spec

EXTREME_IV_HV_MULTIPLE = 1.35
#: Vol stored above this is a percent (25 → 25%), not a fraction (0.25 → 25%).
_PERCENT_VOL_MIN = 3.0

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

# Defined-risk credit and hedged structures. Conservative prefers these (lower short delta).
CONSERVATIVE_STRUCTURES: frozenset[str] = frozenset(
    {
        "Short Iron Condor",
        "Bull Put Spread (credit)",
        "Bear Call Spread (credit)",
        "Married Put",
        "Married Call",
        "Calendar Spread",
        "Diagonal Spread (bullish)",
        "Diagonal Spread (bearish)",
        APEX_STRATEGY_NAME,
    }
)

# Directional debit verticals and long premium already ranked by the §9.1 matrix.
AGGRESSIVE_DIRECTIONAL: frozenset[str] = frozenset(
    {
        "Bull Call Spread",
        "Bear Put Spread",
        "Long Straddle",
        "APEX Benchmark Greeks Strategy",
        "Diagonal Spread (bullish)",
        "Diagonal Spread (bearish)",
    }
)

NEUTRAL_INCOME_STRUCTURES: frozenset[str] = frozenset(
    {
        "Short Iron Condor",
        "Calendar Spread",
    }
)

RISK_PROFILES: frozenset[str] = frozenset({"conservative", "moderate", "aggressive", "custom"})

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
    eligible: bool = True


@dataclass
class StrategyRecommendation:
    best_match: str
    tier: str
    score: float
    auto_exec_eligible: bool
    candidates: list[StrategyCandidate] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)
    gate_reason: str | None = None
    leg_structure: str | None = None
    strategies_evaluated: int = 0
    risk_notes: list[str] = field(default_factory=list)

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
                    "eligible": c.eligible,
                }
                for c in self.candidates
            ],
            "rejection_reasons": self.rejection_reasons,
            "gates": self.gates,
            "gate_reason": self.gate_reason,
            "leg_structure": self.leg_structure,
            "strategies_evaluated": self.strategies_evaluated,
            "risk_notes": list(self.risk_notes),
        }


def _positive_vol(value: Any) -> float | None:
    """A usable IV or HV reading. Missing, zero, and non-finite values are not comparable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def aligned_iv_hv(iv: Any, hv: Any) -> tuple[float, float] | None:
    """IV and HV as positive fractions, or None when either side cannot be compared.

    Does not invent a stand-in. A reading above 3 is a percent (25 means 25%) and is
    rescaled so it can be compared with a fraction (0.25). Zero, missing, and
    non-finite HV never qualify as extreme IV.
    """
    iv_n = _positive_vol(iv)
    hv_n = _positive_vol(hv)
    if iv_n is None or hv_n is None:
        return None
    if iv_n > _PERCENT_VOL_MIN:
        iv_n = iv_n / 100.0
    if hv_n > _PERCENT_VOL_MIN:
        hv_n = hv_n / 100.0
    if iv_n <= 0 or hv_n <= 0 or not math.isfinite(iv_n) or not math.isfinite(hv_n):
        return None
    return iv_n, hv_n


def extreme_iv_overhang(iv: Any, hv: Any) -> bool:
    """True only when both vols are real and positive and IV exceeds HV by more than 35%.

    This is a scoring and warning input. It does not choose or replace the strategy.
    """
    pair = aligned_iv_hv(iv, hv)
    if pair is None:
        return False
    iv_f, hv_f = pair
    return iv_f > hv_f * EXTREME_IV_HV_MULTIPLE


def format_vol_percent(value: Any) -> str | None:
    """IV or HV as a percent with two decimals.

    0.2334 and 23.34 both render as 23.34%. Missing or non-positive values return None.
    """
    number = _positive_vol(value)
    if number is None:
        return None
    if number > _PERCENT_VOL_MIN:
        number = number / 100.0
    return f"{number * 100:.2f}%"


def real_strategy_count() -> int:
    """Registry size excluding advisory stand-ins that have no legs."""
    return sum(1 for spec in STRATEGY_REGISTRY.values() if spec.risk_type != "advisory" and spec.leg_count > 0)


def _score_tier(score: float) -> str:
    if score <= EXECUTION_SCORE_BLOCKED_MAX:
        return "no_trade"
    if score <= SCORE_TIER_WATCHLIST_MAX:
        return "watchlist"
    return "candidate"


def _is_defined_risk(name: str) -> bool:
    if name in UNDEFINED_RISK_STRATEGIES:
        return False
    spec = get_strategy_spec(name)
    if spec is not None and (spec.risk_type != "defined" or spec.leg_count == 0):
        return False
    return True


def _fallback_structure(direction: str) -> str:
    if direction == "bearish":
        return "Bear Put Spread"
    if direction == "neutral":
        return "Long Straddle"
    return "Bull Call Spread"


def _score_token(value: float) -> str:
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def auto_exec_status_line(composite: float, threshold: float, *, defined_risk: bool) -> str | None:
    """Score-versus-minimum line. Eligible when the displayed composite is at or above the saved minimum."""
    if not defined_risk or composite < threshold:
        return None
    return (
        f"Composite score {_score_token(composite)} · "
        f"Your auto-execute minimum {_score_token(threshold)} · "
        f"Auto-execute eligible"
    )


def normalize_risk_profile(risk_profile: str | None) -> str:
    if risk_profile in RISK_PROFILES:
        return str(risk_profile)
    return "moderate"


def order_candidates_for_risk_profile(
    candidates: list[StrategyCandidate],
    risk_profile: str | None,
    *,
    structure_limits: frozenset[str] | None = None,
) -> list[StrategyCandidate]:
    """Reorder eligible defined-risk candidates to complement the saved risk profile.

    Hard gates stay upstream. Undefined-risk names are not promoted. Custom keeps
    the moderate (matrix) order unless ``structure_limits`` names an allowlist.
    """
    profile = normalize_risk_profile(risk_profile)
    ordered = list(candidates)
    if profile == "custom" and structure_limits:
        allowed = [c for c in ordered if c.defined_risk and c.name in structure_limits]
        if allowed:
            return allowed
    if profile == "conservative":
        preferred_ids = {id(c) for c in ordered if c.defined_risk and c.name in CONSERVATIVE_STRUCTURES}
        if not preferred_ids:
            return ordered
        preferred = [c for c in ordered if id(c) in preferred_ids]
        rest = [c for c in ordered if id(c) not in preferred_ids]
        return preferred + rest
    if profile == "aggressive":
        has_directional = any(c.defined_risk and c.name in AGGRESSIVE_DIRECTIONAL for c in ordered)
        has_income = any(c.name in NEUTRAL_INCOME_STRUCTURES for c in ordered)
        if not has_directional or not has_income:
            return ordered
        first_income = next(i for i, c in enumerate(ordered) if c.name in NEUTRAL_INCOME_STRUCTURES)
        late = [
            c
            for c in ordered[first_income:]
            if c.defined_risk and c.name in AGGRESSIVE_DIRECTIONAL
        ]
        if not late:
            return ordered
        late_ids = {id(c) for c in late}
        kept = [c for c in ordered if id(c) not in late_ids]
        insert_at = next(i for i, c in enumerate(kept) if c.name in NEUTRAL_INCOME_STRUCTURES)
        return kept[:insert_at] + late + kept[insert_at:]
    return ordered


def is_defined_risk_strategy(strategy_name: str) -> bool:
    return _is_defined_risk(strategy_name)


def allows_auto_execution(
    strategy_name: str,
    *,
    execution_tier: str,
    composite: float,
    auto_exec_threshold: float = 85.0,
) -> bool:
    """Arm auto-submit from the saved threshold and defined-risk only.

    ``execution_tier`` is a display band. It is not a second score floor
    (50, 72, or a hardcoded 85).
    """
    _ = execution_tier
    if not is_defined_risk_strategy(strategy_name):
        return False
    return composite >= auto_exec_threshold


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


def _registry_miss_note(
    spec: StrategySpec,
    *,
    direction: str,
    iv_cheap: bool,
    iv_rich: bool,
    rsi: float,
    tech_score: float,
    back_month_available: bool,
    apex_eligible: bool,
    catalyst_active: bool,
    delta_theta_ratio: float | None,
) -> str:
    """Short gate phrase already used by the matrix. One note per missed strategy."""
    name = spec.display_name
    if spec.risk_type == "undefined" or name in UNDEFINED_RISK_STRATEGIES:
        return "excluded from automated execution"
    if spec.leg_count == 0 or spec.risk_type == "advisory":
        return name
    meta = DEFINED_RISK_PLAYBOOK.get(name)
    if not meta:
        return "No defined-risk strategy matched the current regime."
    iv_need = meta.get("iv")
    bias = meta.get("bias")
    if iv_need == "cheap" and not iv_cheap:
        return "IV cheap"
    if iv_need == "rich" and not iv_rich:
        return "IV rich"
    if iv_need == "catalyst" and not (apex_eligible and catalyst_active):
        return "Catalyst window active"
    if name in {"Calendar Spread", "Diagonal Spread (bullish)", "Diagonal Spread (bearish)"} and not back_month_available:
        return "Neutral time-spread when back-month chain available"
    if bias == "bullish" and direction != "bullish":
        return "Bullish technical alignment"
    if bias == "bearish" and direction != "bearish":
        return "Bearish technical alignment"
    if name == "Short Iron Condor" and not (40 <= rsi <= 60):
        return "Range-bound RSI"
    if name == "Long Straddle" and direction != "neutral":
        return "Neutral direction"
    if name in {"Bull Call Spread", "Bear Put Spread"} and tech_score <= 80:
        return "Bullish technical alignment" if direction == "bullish" else "Bearish technical alignment"
    if name == "APEX Benchmark Greeks Strategy" and not (delta_theta_ratio and delta_theta_ratio >= 10):
        return "Δ/Θ ratio ≥ 10"
    if name == "Married Put" and direction != "bullish":
        return "Protective hedge expression"
    return "No defined-risk strategy matched the current regime."


def _attach_registry_evaluation(
    eligible: list[StrategyCandidate],
    matrix_matches: list[StrategyCandidate],
    *,
    tier: str,
    direction: str,
    iv_cheap: bool,
    iv_rich: bool,
    rsi: float,
    tech_score: float,
    back_month_available: bool,
    apex_eligible: bool,
    catalyst_active: bool,
    delta_theta_ratio: float | None,
) -> tuple[list[StrategyCandidate], list[str], int]:
    """Score every registry strategy. Misses keep a gate note and are not the Best Match."""
    eligible_names = {c.name for c in eligible}
    matched = {c.name: c for c in matrix_matches}
    for candidate in eligible:
        candidate.eligible = True
    misses: list[StrategyCandidate] = []
    undefined_reasons: list[str] = []
    for spec in STRATEGY_REGISTRY.values():
        if spec.display_name in eligible_names:
            continue
        held = matched.get(spec.display_name)
        if held is not None:
            misses.append(
                StrategyCandidate(
                    name=held.name,
                    score=held.score,
                    tier=held.tier,
                    defined_risk=held.defined_risk,
                    gate_notes=list(held.gate_notes),
                    eligible=False,
                )
            )
            continue
        note = _registry_miss_note(
            spec,
            direction=direction,
            iv_cheap=iv_cheap,
            iv_rich=iv_rich,
            rsi=rsi,
            tech_score=tech_score,
            back_month_available=back_month_available,
            apex_eligible=apex_eligible,
            catalyst_active=catalyst_active,
            delta_theta_ratio=delta_theta_ratio,
        )
        if spec.risk_type == "advisory" or spec.leg_count == 0:
            continue
        if spec.display_name in UNDEFINED_RISK_STRATEGIES:
            undefined_reasons.append(f"{spec.display_name}: {note}")
            continue
        if spec.risk_type == "undefined":
            undefined_reasons.append(f"{spec.display_name}: {note}")
            continue
        misses.append(
            StrategyCandidate(
                name=spec.display_name,
                score=0.0,
                tier=tier,
                defined_risk=_is_defined_risk(spec.display_name) and spec.risk_type == "defined",
                gate_notes=[note],
                eligible=False,
            )
        )
    return eligible + misses, undefined_reasons, real_strategy_count()


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
    risk_profile: str = "moderate",
    structure_limits: frozenset[str] | None = None,
) -> StrategyRecommendation:
    """
    Staged gating: liquidity → defined-risk → data freshness → technical confirmation
    → IV regime → catalyst fit. Returns exactly one real Best Match.

    Score, IV versus HV, earnings proximity, and spread width are warnings.
    They do not replace the ranked structure.
    """
    rejection_reasons: list[str] = []
    gates: dict[str, bool] = {}
    tier = _score_tier(composite)
    comparable = aligned_iv_hv(iv, hv)
    rank_iv, rank_hv = comparable if comparable else (None, None)

    # Gate 1: Data freshness is recorded as a warning. It does not replace the ranked structure.
    gates["data_freshness"] = market.data_fresh

    # Gate 2: Liquidity. A wide chain median is noted; it does not borrow the IV-crush sentence.
    spread_ok = market.spread_pct is None or market.spread_pct <= 10.0
    adv_ok = market.adv is None or market.adv >= 1_000_000
    gates["liquidity"] = spread_ok and adv_ok
    if not adv_ok:
        rejection_reasons.append("ADV below liquidity minimum")

    # Gate 5: Technical confirmation (soft — does not by itself replace a later hard-gate reason)
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
    matrix_matches = _rank_candidates(
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi_v,
        iv=rank_iv,
        hv=rank_hv,
        ivr=ivr,
        tech_score=technical.score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=delta_theta_ratio,
        apex_eligible=apex_eligible,
        back_month_available=back_month_available,
    )
    ranked = order_candidates_for_risk_profile(
        matrix_matches,
        risk_profile,
        structure_limits=structure_limits,
    )
    iv_cheap = rank_iv is not None and rank_hv is not None and (rank_hv - rank_iv) > 0.10
    iv_rich = vol_signal == "sell_premium" or (
        rank_iv is not None and rank_hv is not None and (rank_iv - rank_hv) > 0.10
    )
    candidates, registry_misses, strategies_evaluated = _attach_registry_evaluation(
        ranked,
        matrix_matches,
        tier=tier,
        direction=direction,
        iv_cheap=iv_cheap,
        iv_rich=iv_rich,
        rsi=rsi_v,
        tech_score=technical.score,
        back_month_available=back_month_available,
        apex_eligible=apex_eligible,
        catalyst_active=catalyst_active,
        delta_theta_ratio=delta_theta_ratio,
    )
    rejection_reasons.extend(registry_misses)
    viable = [c for c in candidates if c.defined_risk and c.eligible]
    risk_notes: list[str] = []

    # The saved auto-execution minimum decides acknowledgement. It is not a selection gate.
    gates["composite_tier"] = True

    gates["earnings_blackout"] = catalyst_days is None or int(catalyst_days) > 1
    if catalyst_days is not None and int(catalyst_days) <= 1:
        risk_notes.append("Earnings are within 1 day.")

    if not market.data_fresh:
        risk_notes.append("Market data is stale.")

    if not spread_ok and market.spread_pct is not None:
        risk_notes.append(f"Bid/ask spread is {market.spread_pct:.1f}% of mid.")

    # IV versus HV warns only when the ratio is actually above 1.35. It never renames the structure.
    gates["iv_regime"] = True
    pair = aligned_iv_hv(iv, hv)
    if extreme_iv_overhang(iv, hv) and pair is not None:
        iv_pct = format_vol_percent(pair[0])
        hv_pct = format_vol_percent(pair[1])
        risk_notes.append(f"IV {iv_pct} versus HV {hv_pct} is above 1.35× historical volatility.")

    best = viable[0] if viable else None
    if best is None:
        fallback_name = _fallback_structure(direction)
        best = StrategyCandidate(
            name=fallback_name,
            score=round(composite, 1),
            tier=tier,
            defined_risk=True,
            gate_notes=["Directional structure for this regime."],
            eligible=True,
        )
        candidates = [best, *candidates]

    auto_exec = allows_auto_execution(
        best.name,
        execution_tier="candidate",
        composite=composite,
        auto_exec_threshold=auto_exec_threshold,
    )

    return StrategyRecommendation(
        best_match=best.name,
        tier="candidate" if auto_exec else "watchlist",
        score=composite,
        auto_exec_eligible=auto_exec,
        candidates=candidates,
        rejection_reasons=rejection_reasons,
        gates=gates,
        leg_structure=best.name,
        strategies_evaluated=strategies_evaluated,
        risk_notes=risk_notes,
    )
