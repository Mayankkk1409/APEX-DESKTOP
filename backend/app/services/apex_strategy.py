"""APEX Strategy eligibility module (formerly Gamma Trampoline)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analysis.layers import APEX_STRATEGY_NAME

# Eligibility thresholds per encyclopedia §10 / workspace rules
CATALYST_DAYS_MIN = 5
CATALYST_DAYS_MAX = 10
DELTA_OTM_MIN = 0.15
DELTA_OTM_MAX = 0.25
FRONT_PREMIUM_OFFSET_MIN = 0.50
FRONT_IVR_MIN = 70
MIN_ADV = 5_000_000
MIN_OPEN_INTEREST = 1_000
MAX_SPREAD_PCT = 8.0


@dataclass
class ApexStrategyInput:
    catalyst_days: int | None = None
    term_structure_inverted: bool = False
    front_iv: float | None = None
    back_iv: float | None = None
    front_ivr: float | None = None
    legs_same_strikes: bool = False
    four_leg_structure: bool = False
    call_delta: float | None = None
    put_delta: float | None = None
    front_premium_offset_pct: float | None = None
    adv: float | None = None
    open_interest: int | None = None
    spread_pct: float | None = None


@dataclass
class ApexStrategyEligibility:
    eligible: bool
    strategy_name: str = APEX_STRATEGY_NAME
    rejection_reasons: list[str] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "strategy_name": self.strategy_name,
            "rejection_reasons": self.rejection_reasons,
            "checks_passed": self.checks_passed,
        }


def _delta_in_range(delta: float | None) -> bool:
    if delta is None:
        return False
    abs_delta = abs(delta)
    return DELTA_OTM_MIN <= abs_delta <= DELTA_OTM_MAX


def check_apex_strategy_eligibility(inp: ApexStrategyInput) -> ApexStrategyEligibility:
    """Deterministic eligibility gate for APEX Strategy with explicit rejection reasons."""
    passed: list[str] = []
    rejected: list[str] = []

    if inp.catalyst_days is None:
        rejected.append("No catalyst date available")
    elif not (CATALYST_DAYS_MIN <= inp.catalyst_days <= CATALYST_DAYS_MAX):
        rejected.append(
            f"Catalyst must be {CATALYST_DAYS_MIN}–{CATALYST_DAYS_MAX} days out; got {inp.catalyst_days}"
        )
    else:
        passed.append(f"Catalyst within {CATALYST_DAYS_MIN}–{CATALYST_DAYS_MAX} day window")

    if inp.front_ivr is None:
        rejected.append("Front-week IVR unavailable")
    elif inp.front_ivr <= FRONT_IVR_MIN:
        rejected.append(f"Front-week IVR must be > {FRONT_IVR_MIN}; got {inp.front_ivr:.0f}")
    else:
        passed.append(f"Front-week IVR > {FRONT_IVR_MIN}")

    if not inp.term_structure_inverted:
        rejected.append("IV term structure must be inverted (front IV > back IV)")
    elif inp.front_iv is not None and inp.back_iv is not None and inp.front_iv <= inp.back_iv:
        rejected.append(
            f"Front IV ({inp.front_iv:.3f}) must exceed back IV ({inp.back_iv:.3f})"
        )
    else:
        passed.append("IV term structure inverted (front > back)")

    if not inp.four_leg_structure:
        rejected.append("APEX Strategy requires a 4-leg structure (front/back call + put)")
    elif not inp.legs_same_strikes:
        rejected.append("Front and back expirations must use the same strikes across all legs")
    else:
        passed.append("4-leg structure with matching strikes across expirations")

    call_ok = _delta_in_range(inp.call_delta)
    put_ok = _delta_in_range(inp.put_delta)
    if not call_ok and not put_ok:
        rejected.append(
            f"Strikes must be {DELTA_OTM_MIN:.2f}–{DELTA_OTM_MAX:.2f} delta OTM on call or put leg"
        )
    else:
        passed.append(f"OTM delta within {DELTA_OTM_MIN:.2f}–{DELTA_OTM_MAX:.2f} band")

    if inp.front_premium_offset_pct is None:
        rejected.append("Front-week premium offset could not be computed")
    elif inp.front_premium_offset_pct < FRONT_PREMIUM_OFFSET_MIN:
        rejected.append(
            f"Front-week premium must offset ≥{int(FRONT_PREMIUM_OFFSET_MIN * 100)}% of back-week cost; "
            f"got {inp.front_premium_offset_pct * 100:.0f}%"
        )
    else:
        passed.append(f"Front-week premium offset ≥{int(FRONT_PREMIUM_OFFSET_MIN * 100)}%")

    if inp.adv is not None and inp.adv < MIN_ADV:
        rejected.append(f"ADV below minimum ({inp.adv:,.0f} < {MIN_ADV:,})")
    elif inp.adv is not None:
        passed.append("ADV liquidity gate passed")

    if inp.open_interest is not None and inp.open_interest < MIN_OPEN_INTEREST:
        rejected.append(f"Open interest below minimum ({inp.open_interest} < {MIN_OPEN_INTEREST})")
    elif inp.open_interest is not None:
        passed.append("Open interest gate passed")

    if inp.spread_pct is not None and inp.spread_pct > MAX_SPREAD_PCT:
        rejected.append(f"Bid/ask spread {inp.spread_pct:.1f}% exceeds {MAX_SPREAD_PCT}% limit")
    elif inp.spread_pct is not None:
        passed.append("Spread within liquidity gate")

    return ApexStrategyEligibility(
        eligible=len(rejected) == 0,
        rejection_reasons=rejected,
        checks_passed=passed,
    )


def _contract_mid(contract: dict[str, Any] | None) -> float | None:
    if not contract:
        return None
    bid, ask = contract.get("bid"), contract.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    last = contract.get("last")
    return float(last) if last is not None else None


def _pick_otm_contract(
    contracts: list[dict[str, Any]],
    side: str,
    *,
    delta_target: float = 0.20,
) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike") is not None]
    if not pool:
        return None
    if side == "call":
        pool.sort(key=lambda c: abs((c.get("delta") or 0) - delta_target))
    else:
        pool.sort(key=lambda c: abs((c.get("delta") or 0) + delta_target))
    return pool[0]


def _contract_at_strike(contracts: list[dict[str, Any]], side: str, strike: float) -> dict[str, Any] | None:
    return next(
        (
            c
            for c in contracts
            if c.get("side") == side and c.get("strike") is not None and abs(float(c["strike"]) - strike) < 0.01
        ),
        None,
    )


def build_apex_strategy_input_from_scan(
    *,
    catalyst_days: int | None,
    vol_layer: dict[str, Any],
    chain_analysis: dict[str, Any],
    contracts: list[dict[str, Any]] | None = None,
    back_month_contracts: list[dict[str, Any]] | None = None,
) -> ApexStrategyInput:
    """Build eligibility input from scan-layer payloads — never fabricates structure eligibility."""
    term = vol_layer.get("term_structure") or {}
    front_iv = term.get("front_iv") or vol_layer.get("iv")
    back_iv = term.get("back_iv")

    front_rows = contracts or chain_analysis.get("contracts") or []
    back_rows = back_month_contracts or []

    call_delta = put_delta = None
    spread_pct = None
    min_oi = None
    for c in front_rows + back_rows:
        side = c.get("side")
        delta = c.get("delta")
        if side == "call" and delta is not None:
            call_delta = float(delta)
        if side == "put" and delta is not None:
            put_delta = float(delta)
        bid, ask = c.get("bid"), c.get("ask")
        if bid and ask and ask > 0:
            mid = (float(bid) + float(ask)) / 2
            if mid > 0:
                sp = (float(ask) - float(bid)) / mid * 100
                spread_pct = sp if spread_pct is None else min(spread_pct, sp)
        oi = c.get("open_interest")
        if oi is not None:
            min_oi = int(oi) if min_oi is None else min(min_oi, int(oi))

    summary = chain_analysis.get("summary") or {}
    median_spread = summary.get("median_spread_pct")
    if spread_pct is None and median_spread is not None:
        spread_pct = float(median_spread)

    inverted = bool(term.get("inverted")) or (
        front_iv is not None and back_iv is not None and float(front_iv) > float(back_iv)
    )

    four_leg_structure = False
    legs_same_strikes = False
    front_premium_offset_pct: float | None = None

    if front_rows and back_rows:
        front_call = _pick_otm_contract(front_rows, "call")
        front_put = _pick_otm_contract(front_rows, "put")
        back_call = (
            _contract_at_strike(back_rows, "call", float(front_call["strike"]))
            if front_call and front_call.get("strike") is not None
            else None
        )
        back_put = (
            _contract_at_strike(back_rows, "put", float(front_put["strike"]))
            if front_put and front_put.get("strike") is not None
            else None
        )
        four_leg_structure = all(c is not None for c in (front_call, front_put, back_call, back_put))
        if four_leg_structure and front_call and front_put and back_call and back_put:
            legs_same_strikes = (
                abs(float(front_call["strike"]) - float(back_call["strike"])) < 0.01
                and abs(float(front_put["strike"]) - float(back_put["strike"])) < 0.01
            )
            front_prem = (_contract_mid(front_call) or 0) + (_contract_mid(front_put) or 0)
            back_prem = (_contract_mid(back_call) or 0) + (_contract_mid(back_put) or 0)
            if back_prem > 0:
                front_premium_offset_pct = front_prem / back_prem
            if front_call.get("delta") is not None:
                call_delta = float(front_call["delta"])
            if front_put.get("delta") is not None:
                put_delta = float(front_put["delta"])

    return ApexStrategyInput(
        catalyst_days=catalyst_days,
        term_structure_inverted=inverted,
        front_iv=float(front_iv) if front_iv is not None else None,
        back_iv=float(back_iv) if back_iv is not None else None,
        front_ivr=float(vol_layer["iv_rank"]) if vol_layer.get("iv_rank") is not None else None,
        legs_same_strikes=legs_same_strikes,
        four_leg_structure=four_leg_structure,
        call_delta=call_delta,
        put_delta=put_delta,
        front_premium_offset_pct=front_premium_offset_pct,
        adv=vol_layer.get("adv"),
        open_interest=min_oi,
        spread_pct=spread_pct,
    )
