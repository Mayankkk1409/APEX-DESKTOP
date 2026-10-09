"""Deterministic strategy recommendation engine with staged gating."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

from app.analysis.gate_config import (
    IV_MISMATCH_VOL_POINTS,
    LONG_VEGA_RICH_PENALTY,
    PLAIN_LONG_PREMIUM,
    assess_vol_regime,
    term_structure_inversion,
)
from app.analysis.layers import (
    APEX_STRATEGY_NAME,
    EXECUTION_SCORE_BLOCKED_MAX,
    SCORE_TIER_WATCHLIST_MAX,
)
from app.services.apex_strategy import (
    GAMMA_TRAMPOLINE_NAME,
    ApexStrategyEligibility,
    ApexStrategyInput,
    check_apex_strategy_eligibility,
)
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
        GAMMA_TRAMPOLINE_NAME,
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
    GAMMA_TRAMPOLINE_NAME: {"bias": "neutral", "iv": "catalyst"},
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
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)


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
                    "score_breakdown": list(c.score_breakdown),
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


def format_iv_rank(value: Any) -> str:
    """IV rank for a card: a whole number or one decimal. Never the raw float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    rounded = round(number, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def format_iv_rank_with_reason(value: Any, reason: str | None = None) -> str:
    """IV rank text for a card. A missing rank carries a reason, never a bare dash."""
    shown = format_iv_rank(value)
    if shown != "—":
        return shown
    detail = str(reason or "").strip().lstrip("—").strip()
    if not detail:
        detail = "IV rank is unavailable because published IV history is missing."
    return f"unavailable: {detail}"


def vol_regime_phrase(iv: Any, hv: Any, vol_signal: str, iv_rank: Any = None) -> str:
    """Card label for the one IV-versus-HV regime rule."""
    return assess_vol_regime(iv=iv, hv=hv, iv_rank=iv_rank, vol_signal=vol_signal).display


def record_ledger(
    *,
    scan_id: str,
    kind: Literal["value", "gate", "candidate", "score"],
    key: str,
    value: Any,
    inputs: dict[str, Any],
    fn: str,
    source: str = "strategy_engine",
) -> None:
    """Persist one frozen ledger row. The contracts stub still drops its own calls."""
    from app.contracts import LedgerEntry
    from app.services.evidence_ledger import record

    record(
        LedgerEntry(
            scanId=scan_id or "scan",
            kind=kind,
            key=key,
            value=value,
            inputs=inputs,
            source=source,
            feed=None,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            fn=fn,
        )
    )


def earnings_position_note(
    strategy_name: str,
    *,
    days: int | None,
    confirmed: bool,
) -> tuple[bool, str | None]:
    """Blackout note for a new position.

    A missing date is unconfirmed and is not a blackout. A confirmed date
    inside 1 day blocks auto-execute except for APEX Strategy.
    """
    if not confirmed:
        return False, "Earnings date is unconfirmed."
    if days is not None and int(days) <= 1:
        return strategy_name != APEX_STRATEGY_NAME, "Earnings are within 1 day."
    return False, None


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


def _fallback_structure(direction: str, *, ivr: float | None = None) -> str:
    if ivr is not None and ivr > 70:
        if direction == "bearish":
            return "Bear Put Spread"
        if direction == "neutral":
            return "Short Iron Condor"
        return "Bull Call Spread"
    if direction == "bearish":
        return "Bear Put Spread"
    if direction == "neutral":
        return "Long Straddle"
    return "Bull Call Spread"


def _score_token(value: float) -> str:
    """One decimal in strategy sentences. Does not change the score."""
    return f"{float(value):.1f}"


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
            if c.defined_risk
            and c.name in AGGRESSIVE_DIRECTIONAL
            and not _carries_long_vega_penalty(c)
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


_LONG_VEGA_NAMES = frozenset(
    {
        "Long Call",
        "Long Put",
        "Married Put",
        "Long Straddle",
        "Long Strangle",
        "APEX Benchmark Greeks Strategy",
        APEX_STRATEGY_NAME,
        GAMMA_TRAMPOLINE_NAME,
    }
)
_SHORT_VEGA_NAMES = frozenset(
    {
        "Short Iron Condor",
        "Bull Put Spread (credit)",
        "Bear Call Spread (credit)",
        "Collar",
        "Protective Collar",
    }
)
_LONG_PUT_HEDGES = frozenset({"Married Put", "Long Put"})
_VEGA_CACHE: dict[str, str] = {}


def _time_spread(name: str) -> bool:
    return "Diagonal" in name or "Calendar" in name or name in {APEX_STRATEGY_NAME, GAMMA_TRAMPOLINE_NAME}


def strategy_vega_sign(name: str) -> str:
    """Long, short, or neutral. Knowledge-base text wins when it names the sign."""
    cached = _VEGA_CACHE.get(name)
    if cached is not None:
        return cached
    sign = "neutral"
    if name in _SHORT_VEGA_NAMES:
        sign = "short"
    elif name in _LONG_VEGA_NAMES or _time_spread(name):
        sign = "long"
    try:
        from app.strategies.knowledge_base import entry_for

        entry = entry_for(name)
    except Exception:
        entry = None
    if entry is not None:
        explicit = getattr(entry, "vega_sign", None)
        if explicit in {"long", "short", "neutral"}:
            sign = str(explicit)
        else:
            text = str(getattr(entry, "greeks_profile", "") or "").lower()
            if "long vega" in text or "net long vega" in text:
                sign = "long"
            elif "short vega" in text:
                sign = "short"
    _VEGA_CACHE[name] = sign
    return sign


def _carries_long_vega_penalty(candidate: StrategyCandidate) -> bool:
    return any(str(note).startswith("Long-vega penalty:") for note in candidate.gate_notes)


def _apply_long_vega_penalty(candidates: list[StrategyCandidate], *, rich: bool, inverted: bool) -> None:
    if not rich:
        return
    for candidate in candidates:
        if strategy_vega_sign(candidate.name) != "long":
            continue
        if inverted and _time_spread(candidate.name):
            note = (
                "Term-structure inversion justifies the long vega: front IV is at least 1.25 times back IV."
            )
            if note not in candidate.gate_notes:
                candidate.gate_notes.append(note)
            continue
        candidate.score = round(float(candidate.score) - LONG_VEGA_RICH_PENALTY, 1)
        note = (
            f"Long-vega penalty: {candidate.name} is long vega in a rich IV regime "
            f"({LONG_VEGA_RICH_PENALTY:g} points versus the {IV_MISMATCH_VOL_POINTS:.0f} vol point threshold). "
            "A long-vega structure in a sell-premium regime "
            "is penalized unless term-structure inversion justifies a diagonal or calendar."
        )
        if note not in candidate.gate_notes:
            candidate.gate_notes.append(note)


def _parse_span_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _long_option_side(name: str) -> str | None:
    """The long option side a time spread would buy. None when the chain may use either side."""
    lowered = name.lower()
    if "diagonal" in lowered and "bull" in lowered:
        return "call"
    if "diagonal" in lowered and "bear" in lowered:
        return "put"
    return None


def long_leg_iv_from_chain(
    contracts: Any,
    *,
    side: str | None,
    spot: Any,
) -> float | None:
    """Nearest listed strike's IV on the live chain. None when that IV is not on the chain."""
    rows: list[tuple[float, float]] = []
    spot_n = spot if isinstance(spot, (int, float)) and not isinstance(spot, bool) else None
    for raw in contracts or []:
        row = raw if isinstance(raw, dict) else None
        if row is None and hasattr(raw, "model_dump"):
            row = raw.model_dump()
        if not isinstance(row, dict):
            continue
        iv = row.get("iv")
        if isinstance(iv, bool) or not isinstance(iv, (int, float)):
            continue
        if side is not None and str(row.get("side") or "") != side:
            continue
        strike = row.get("strike")
        if spot_n is not None and isinstance(strike, (int, float)) and not isinstance(strike, bool):
            distance = abs(float(strike) - float(spot_n))
        else:
            distance = 0.0
        rows.append((distance, float(iv)))
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    return rows[0][1]


def measure_event_vega(
    *,
    earnings_on: Any,
    short_expiry: Any,
    long_expiry: Any,
    long_leg_iv: Any,
    normal_iv: Any,
    long_side: str | None,
) -> tuple[float | None, str | None]:
    """Vol points to subtract when only the long expiry spans earnings.

    The points are the long-leg IV premium over normal IV from the chain.
    A missing IV returns no number and must not be subtracted.
    """
    earn = _parse_span_day(earnings_on)
    short_on = _parse_span_day(short_expiry)
    long_on = _parse_span_day(long_expiry)
    if earn is None or short_on is None or long_on is None:
        return None, None
    if short_on >= earn or long_on <= earn:
        return None, None
    side = long_side or "option"
    base = (
        f"Event-vega penalty: the long {side} expiring {long_on.isoformat()} spans earnings on {earn.isoformat()}. "
        f"The short expiry {short_on.isoformat()} is before the event."
    )
    from app.analysis.gate_config import _as_fraction

    long_f = _as_fraction(long_leg_iv)
    normal = _as_fraction(normal_iv)
    if long_f is None or normal is None:
        return None, base + " Long-leg IV premium over normal IV could not be measured."
    premium = (long_f - normal) * 100.0
    shown = round(premium, 2)
    if shown <= 0:
        return None, (
            base
            + f" Long-leg IV {long_f * 100:.2f}% is {shown:.2f} vol points versus normal IV {normal * 100:.2f}%."
            + " No penalty is subtracted."
        )
    return shown, (
        base
        + f" Long-leg IV {long_f * 100:.2f}% is {shown:.2f} vol points over normal IV {normal * 100:.2f}%."
        + f" Penalty {shown:.2f} points."
    )


def _event_vega_for_candidate(name: str, span: dict[str, Any]) -> tuple[float | None, str | None]:
    side = _long_option_side(name)
    iv = span.get("long_leg_iv")
    if iv is None:
        iv = long_leg_iv_from_chain(span.get("contracts"), side=side, spot=span.get("spot"))
    return measure_event_vega(
        earnings_on=span.get("earnings_date"),
        short_expiry=span.get("short_expiry"),
        long_expiry=span.get("long_expiry"),
        long_leg_iv=iv,
        normal_iv=span.get("normal_iv"),
        long_side=side,
    )


def _apply_event_vega_penalty(candidates: list[StrategyCandidate], span: dict[str, Any] | None) -> None:
    """Subtract the measured long-leg premium before rank. Do not invent the points."""
    if not span:
        return
    for candidate in candidates:
        if not candidate.eligible or not _time_spread(candidate.name):
            continue
        if any(str(note).startswith("Event-vega penalty:") for note in candidate.gate_notes):
            continue
        points, note = _event_vega_for_candidate(candidate.name, span)
        if note is None:
            continue
        row: dict[str, Any] = {
            "label": "Event-vega penalty",
            "value": None if points is None else float(points),
            "note": note,
        }
        if points is not None and points > 0:
            before = float(candidate.score)
            candidate.score = round(before - float(points), 1)
            row["score_before"] = before
            row["score_after"] = float(candidate.score)
        candidate.score_breakdown.append(row)
        candidate.gate_notes.append(note)


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
    front_iv: Any = None,
    back_iv: Any = None,
    inversion_flagged: bool = False,
    event_span: dict[str, Any] | None = None,
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

    regime = assess_vol_regime(
        iv=iv,
        hv=hv,
        iv_rank=ivr,
        vol_signal=vol_signal,
        front_iv=front_iv,
        back_iv=back_iv,
        inversion_flagged=inversion_flagged,
    )
    # The short label is the one rule. A caller vol_signal can still open the other
    # family only when the primary band is the ±5 tie, so a decisive IV-versus-HV
    # gap is not overridden.
    iv_cheap = regime.short == "buy premium" or (
        vol_signal == "buy_premium" and regime.short != "sell premium"
    )
    iv_rich = regime.short == "sell premium" or (
        vol_signal == "sell_premium" and regime.short != "buy premium"
    )
    rule_rich = regime.short == "sell premium"

    if apex_eligible and catalyst_active:
        add(GAMMA_TRAMPOLINE_NAME, 14.0, ["Gamma Trampoline earnings gates passed", "Catalyst window active"])

    if iv_cheap and tech_score > 80 and direction == "bullish":
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
    if direction == "bullish":
        add("Married Put", 2.0, ["Protective hedge expression"])
    if rule_rich and direction == "bullish" and any(row.name in _LONG_PUT_HEDGES for row in candidates):
        add(
            "Collar",
            3.0,
            ["Rich-IV hedge alternative: a short call finances the long put"],
        )
    if back_month_available:
        if direction == "bullish":
            add("Diagonal Spread (bullish)", 2.0, ["Directional time spread"])
        if direction == "bearish":
            add("Diagonal Spread (bearish)", 2.0, ["Directional time spread"])
        add("Calendar Spread", 1.0, ["Neutral time-spread when back-month chain available"])

    _apply_long_vega_penalty(candidates, rich=rule_rich, inverted=regime.inverted)
    _apply_event_vega_penalty(candidates, event_span)
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
                    score_breakdown=list(held.score_breakdown),
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
    lead = (
        f"Neutral {strategy_name} selected despite {direction} technical bias "
        f"(score {tech_score:.1f}). "
        f"Volatility regime '{vol_signal.replace('_', ' ')}' overrides directional tilt. "
    )
    if meta.get("iv") == "rich" or strategy_name == "Short Iron Condor":
        return lead + "This sells an OTM put spread and an OTM call spread."
    if "Straddle" in strategy_name:
        return lead + "This buys the call and the put at the same strike."
    if "Calendar" in strategy_name:
        return lead + "This sells the near option and buys the same strike in a later expiry."
    if strategy_name == APEX_STRATEGY_NAME:
        return (
            lead
            + "This buys the back-week call and put and sells the same strikes in the front week."
        )
    return lead.rstrip()


def _place_candidate(candidates: list[StrategyCandidate], candidate: StrategyCandidate) -> None:
    """Keep an evaluated strategy on the list. An eligible pass is inserted by score."""
    for index, existing in enumerate(candidates):
        if existing.name != candidate.name:
            continue
        if candidate.eligible and candidate.score >= existing.score:
            existing.score = candidate.score
            existing.eligible = True
            existing.defined_risk = candidate.defined_risk
            existing.gate_notes = list(candidate.gate_notes)
            existing.score_breakdown = list(candidate.score_breakdown)
            existing.tier = candidate.tier
            row = candidates.pop(index)
            for insert_at, other in enumerate(candidates):
                if other.eligible and other.score < row.score:
                    candidates.insert(insert_at, row)
                    return
            candidates.append(row)
        elif not existing.eligible and not candidate.eligible:
            existing.gate_notes = list(candidate.gate_notes)
        return
    if not candidate.eligible:
        candidates.append(candidate)
        return
    for index, existing in enumerate(candidates):
        if existing.eligible and existing.score < candidate.score:
            candidates.insert(index, candidate)
            return
    candidates.insert(0, candidate)


def _merge_change11_evaluations(
    candidates: list[StrategyCandidate],
    *,
    composite: float,
    tier: str,
    direction: str,
    sentiment_score: float | None,
    sentiment_bias: str | None,
    iv_rank: float | None,
    rsi: float | None,
    rule_context: dict[str, Any] | None,
    apex_input: ApexStrategyInput | None,
    apex_result: ApexStrategyEligibility | None,
    rich: bool = False,
    inverted: bool = False,
    event_span: dict[str, Any] | None = None,
) -> None:
    """Score Rule 1, Rule 2, and Gamma Trampoline on every scan. A failed gate stays ineligible."""
    from app.services.benchmark_greeks import RULE2_NAMES, evaluate_rule1, evaluate_rule2

    ctx = rule_context or {}
    rule1 = evaluate_rule1(
        technical_direction=ctx.get("technical_direction", direction),
        sentiment_score=ctx.get("sentiment_score", sentiment_score),
        sentiment_bias=ctx.get("sentiment_bias", sentiment_bias),
        delta=ctx.get("delta"),
        spot=ctx.get("spot"),
        theta_per_share=ctx.get("theta_per_share"),
        mid=ctx.get("mid"),
        dte=ctx.get("dte"),
        contract_iv=ctx.get("contract_iv"),
        hv20=ctx.get("hv20"),
        bid=ctx.get("bid"),
        ask=ctx.get("ask"),
        spread_pct=ctx.get("spread_pct"),
    )
    rule1_score = round(min(98.0, float(composite) + 11.0), 1)
    rule1_notes = list(rule1.passed if rule1.eligible else rule1.reasons)
    rule1_row = StrategyCandidate(
        name="APEX Benchmark Greeks Strategy",
        score=rule1_score if rule1.eligible else 0.0,
        tier=tier,
        defined_risk=True,
        gate_notes=rule1_notes,
        eligible=rule1.eligible,
    )
    if rule1.eligible:
        _apply_long_vega_penalty([rule1_row], rich=rich, inverted=inverted)
    _place_candidate(candidates, rule1_row)
    rule2 = evaluate_rule2(
        technical_direction=ctx.get("technical_direction", direction),
        sentiment_score=ctx.get("sentiment_score", sentiment_score),
        sentiment_bias=ctx.get("sentiment_bias", sentiment_bias),
        iv_rank=ctx.get("iv_rank", iv_rank),
        rsi=ctx.get("rsi", rsi),
        dte=ctx.get("rule2_dte", ctx.get("dte")),
        contracts=ctx.get("contracts"),
        spot=ctx.get("spot"),
    )
    structure_name = RULE2_NAMES.get(rule2.structure or "", "")
    if rule2.eligible and structure_name:
        _place_candidate(
            candidates,
            StrategyCandidate(
                name=structure_name,
                score=round(min(98.0, float(composite) + 9.0), 1),
                tier=tier,
                defined_risk=True,
                gate_notes=["APEX Benchmark Greeks Strategy Rule 2", *rule2.passed],
                eligible=True,
            ),
        )
    else:
        rule2_notes = [f"Rule 2: {reason}" for reason in rule2.reasons] or ["Rule 2 gates did not pass"]
        held = next((row for row in candidates if row.name == "APEX Benchmark Greeks Strategy"), None)
        if held is not None and not held.eligible:
            held.gate_notes = [*held.gate_notes, *rule2_notes]
        elif held is None:
            _place_candidate(
                candidates,
                StrategyCandidate(
                    name="APEX Benchmark Greeks Strategy",
                    score=0.0,
                    tier=tier,
                    defined_risk=True,
                    gate_notes=rule2_notes,
                    eligible=False,
                ),
            )
    gamma_reasons = list(apex_result.rejection_reasons) if apex_result is not None else ["Earnings date is missing."]
    gamma_ok = bool(apex_result and apex_result.eligible)
    if not any(c.name == GAMMA_TRAMPOLINE_NAME for c in candidates):
        gamma_row = StrategyCandidate(
            name=GAMMA_TRAMPOLINE_NAME,
            score=round(min(98.0, float(composite) + 14.0), 1) if gamma_ok else 0.0,
            tier=tier,
            defined_risk=True,
            gate_notes=(
                ["Gamma Trampoline earnings gates passed", *(apex_result.checks_passed if apex_result else [])]
                if gamma_ok
                else [
                    *(apex_result.checks_passed if apex_result else []),
                    *gamma_reasons,
                ]
            ),
            eligible=gamma_ok,
        )
        if gamma_ok:
            _apply_long_vega_penalty([gamma_row], rich=rich, inverted=inverted)
            _apply_event_vega_penalty([gamma_row], event_span)
        _place_candidate(candidates, gamma_row)
    _ = apex_input


def _evaluate_rich_iv_collar(
    candidates: list[StrategyCandidate],
    *,
    best: StrategyCandidate,
    tier: str,
    rich: bool,
    earnings_context: bool,
) -> tuple[StrategyCandidate, str] | None:
    """Score a collar against a long-put hedge when IV is rich and an event is in play."""
    if not rich or not earnings_context:
        return None
    hedges = [row for row in candidates if row.eligible and row.name in _LONG_PUT_HEDGES]
    if not hedges:
        return None
    hedge = max(hedges, key=lambda row: row.score)
    collar_score = round(float(hedge.score) + LONG_VEGA_RICH_PENALTY, 1)
    collar = StrategyCandidate(
        name="Collar",
        score=collar_score,
        tier=tier,
        defined_risk=_is_defined_risk("Collar"),
        gate_notes=[
            "Short call finances the long put in a rich IV regime.",
            f"{hedge.name} scored {hedge.score:g} after the long-vega penalty.",
        ],
        eligible=True,
    )
    winner = best
    if winner.name in _LONG_PUT_HEDGES and collar_score > float(winner.score):
        winner = collar
    if not any(row.name == "Collar" for row in candidates):
        if winner.name == "Collar":
            candidates.insert(0, collar)
        else:
            candidates.append(collar)
    band = f"{IV_MISMATCH_VOL_POINTS:.0f}"
    if winner.name == "Collar":
        reason = (
            f"Collar ranked first at {collar_score:g} in a rich IV regime versus the {band} vol point threshold. "
            f"The short call finances the long put. {hedge.name} scored {hedge.score:g} after the long-vega penalty."
        )
    else:
        reason = (
            f"{winner.name} ranked first at {winner.score:g} in a rich IV regime versus the {band} vol point threshold. "
            f"Collar scored {collar_score:g} because a short call would finance the long put. "
            f"{hedge.name} scored {hedge.score:g} after the long-vega penalty. {winner.name} leads the collar on score."
        )
    return winner, reason


def _record_recommendation(
    *,
    scan_id: str,
    gates: dict[str, bool],
    candidates: list[StrategyCandidate],
    best: StrategyCandidate,
    regime: Any,
    composite: float,
) -> None:
    from app.contracts import VolRegime

    record_ledger(
        scan_id=scan_id,
        kind="value",
        key="vol_regime",
        value=VolRegime(
            ivMinusHvPts=regime.iv_minus_hv_pts,
            ivToHv=regime.iv_to_hv,
            ivRank=regime.iv_rank,
            verdict=regime.verdict,
            rule=regime.rule,
        ),
        inputs={
            "iv_minus_hv_pts": regime.iv_minus_hv_pts,
            "iv_to_hv": regime.iv_to_hv,
            "iv_rank": regime.iv_rank,
        },
        fn="assess_vol_regime",
        source="strategy_recommendation",
    )
    for key, passed in gates.items():
        record_ledger(
            scan_id=scan_id,
            kind="gate",
            key=str(key),
            value=bool(passed),
            inputs={},
            fn="recommend_strategy",
            source="strategy_recommendation",
        )
    for index, candidate in enumerate(candidates):
        record_ledger(
            scan_id=scan_id,
            kind="candidate",
            key=candidate.name,
            value={"score": candidate.score, "eligible": candidate.eligible, "order": index},
            inputs={"gate_notes": list(candidate.gate_notes), "breakdown": list(candidate.score_breakdown)},
            fn="recommend_strategy",
            source="strategy_recommendation",
        )
        penalty_note = next(
            (note for note in candidate.gate_notes if str(note).startswith("Event-vega penalty:")),
            None,
        )
        record_ledger(
            scan_id=scan_id,
            kind="score",
            key=f"{candidate.name}:score",
            value=candidate.score,
            inputs={
                "eligible": candidate.eligible,
                "event_vega_note": penalty_note,
                "breakdown": list(candidate.score_breakdown),
            },
            fn="recommend_strategy",
            source="strategy_recommendation",
        )
        if penalty_note is not None:
            measured = next(
                (
                    row.get("value")
                    for row in candidate.score_breakdown
                    if row.get("label") == "Event-vega penalty"
                ),
                None,
            )
            record_ledger(
                scan_id=scan_id,
                kind="score",
                key=f"{candidate.name}:event_vega_penalty",
                value=penalty_note,
                inputs={
                    "score": candidate.score,
                    "strategy": candidate.name,
                    "points": measured,
                    "breakdown": [
                        row
                        for row in candidate.score_breakdown
                        if row.get("label") == "Event-vega penalty"
                    ],
                },
                fn="recommend_strategy",
                source="strategy_recommendation",
            )
    record_ledger(
        scan_id=scan_id,
        kind="score",
        key="rank",
        value=best.name,
        inputs={"score": best.score, "composite": composite},
        fn="recommend_strategy",
        source="strategy_recommendation",
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
    earnings_date_confirmed: bool | None = None,
    delta_theta_ratio: float | None = None,
    apex_input: ApexStrategyInput | None = None,
    auto_exec_threshold: float = 85.0,
    back_month_available: bool = False,
    risk_profile: str = "moderate",
    structure_limits: frozenset[str] | None = None,
    rule_context: dict[str, Any] | None = None,
    sentiment_bias: str | None = None,
    event_span: dict[str, Any] | None = None,
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

    # Gate 6: Gamma Trampoline earnings gates. A miss does not replace the ranked structure.
    apex_result: ApexStrategyEligibility | None
    if apex_input is None:
        apex_input = ApexStrategyInput()
    apex_result = check_apex_strategy_eligibility(apex_input)
    apex_eligible = apex_result.eligible
    gates["catalyst_fit"] = apex_eligible or not catalyst_active
    if not apex_eligible:
        rejection_reasons.extend(apex_result.rejection_reasons)

    direction = market.direction
    rsi_v = rsi if rsi is not None else 50.0
    regime = assess_vol_regime(
        iv=rank_iv,
        hv=rank_hv,
        iv_rank=ivr,
        vol_signal=vol_signal,
        front_iv=apex_input.front_iv,
        back_iv=apex_input.back_iv,
        inversion_flagged=bool(apex_input.term_structure_inverted),
    )
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
        front_iv=apex_input.front_iv,
        back_iv=apex_input.back_iv,
        inversion_flagged=bool(apex_input.term_structure_inverted),
        event_span=event_span,
    )
    ranked = order_candidates_for_risk_profile(
        matrix_matches,
        risk_profile,
        structure_limits=structure_limits,
    )
    iv_cheap = regime.short == "buy premium"
    iv_rich = regime.short == "sell premium"
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
    _merge_change11_evaluations(
        candidates,
        composite=composite,
        tier=tier,
        direction=direction,
        sentiment_score=sentiment_score,
        sentiment_bias=sentiment_bias,
        iv_rank=ivr,
        rsi=rsi_v,
        rule_context=rule_context,
        apex_input=apex_input,
        apex_result=apex_result,
        rich=iv_rich,
        inverted=regime.inverted,
        event_span=event_span,
    )
    viable = [c for c in candidates if c.defined_risk and c.eligible]
    if ivr is not None and float(ivr) > 70:
        viable = [c for c in viable if c.name not in PLAIN_LONG_PREMIUM]
    if normalize_risk_profile(risk_profile) == "custom" and structure_limits:
        limited = [c for c in viable if c.name in structure_limits]
        if limited:
            viable = limited
    risk_notes: list[str] = []

    # The saved auto-execution minimum decides acknowledgement. It is not a selection gate.
    gates["composite_tier"] = True

    earnings_within_day = (
        earnings_date_confirmed is not False
        and catalyst_days is not None
        and int(catalyst_days) <= 1
    )
    gates["earnings_blackout"] = not earnings_within_day
    if earnings_date_confirmed is False:
        risk_notes.append("Earnings date is unconfirmed.")
    elif earnings_within_day:
        risk_notes.append("Earnings are within 1 day.")

    if not market.data_fresh:
        risk_notes.append("Market data is stale.")

    if not spread_ok and market.spread_pct is not None:
        risk_notes.append(f"Bid/ask spread is {market.spread_pct:.1f}% of mid.")

    # IV versus HV is not a stand-aside multiple. Rule 1 applies IV < HV only to Rule 1 names.
    gates["iv_regime"] = True

    best = viable[0] if viable else None
    if best is None:
        fallback_name = _fallback_structure(direction, ivr=float(ivr) if ivr is not None else None)
        best = StrategyCandidate(
            name=fallback_name,
            score=round(composite, 1),
            tier=tier,
            defined_risk=True,
            gate_notes=["Directional structure for this regime."],
            eligible=True,
        )
        candidates = [best, *candidates]

    rank_note = _evaluate_rich_iv_collar(
        candidates,
        best=best,
        tier=tier,
        rich=iv_rich,
        earnings_context=catalyst_active or catalyst_days is not None,
    )
    if rank_note is not None:
        best = rank_note[0]
        risk_notes.append(rank_note[1])
    for note in best.gate_notes:
        if str(note).startswith("Event-vega penalty:") and note not in risk_notes:
            risk_notes.append(note)

    earnings_block = earnings_within_day and best.name not in {APEX_STRATEGY_NAME, GAMMA_TRAMPOLINE_NAME}
    auto_exec = allows_auto_execution(
        best.name,
        execution_tier="candidate",
        composite=composite,
        auto_exec_threshold=auto_exec_threshold,
    ) and not earnings_block

    _record_recommendation(
        scan_id=market.symbol,
        gates=gates,
        candidates=candidates,
        best=best,
        regime=regime,
        composite=composite,
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
