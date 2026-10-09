"""Gamma Trampoline eligibility. Every earnings gate must pass.

The same four legs without those gates are a standard double calendar.
The trademark name is used only when the gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analysis.gate_config import (
    gamma_adv_min,
    gamma_back_week_days,
    gamma_back_week_tolerance_days,
    gamma_earnings_days_max,
    gamma_earnings_days_min,
    gamma_front_back_iv_ratio_min,
    gamma_front_iv_rank_min,
    gamma_history_hits_min,
    gamma_history_lookback,
    gamma_open_interest_min,
    gamma_spread_max,
)
GAMMA_TRAMPOLINE_NAME = "Gamma Trampoline™"
DOUBLE_CALENDAR_NAME = "Double Calendar"

# Named defaults. The live values are read from settings inside the gate.
CATALYST_DAYS_MIN = 5
CATALYST_DAYS_MAX = 10
FRONT_IVR_MIN = 70
MIN_ADV = 5_000_000
MIN_OPEN_INTEREST = 1_000
MAX_SPREAD_PCT = 8.0
FRONT_BACK_IV_RATIO_MIN = 1.25


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
    earnings_date_confirmed: bool = False
    earnings_history_hits: int | None = None
    earnings_history_count: int | None = None
    front_expiry_listed: bool = False
    back_expiry_listed: bool = False


@dataclass
class ApexStrategyEligibility:
    eligible: bool
    strategy_name: str = GAMMA_TRAMPOLINE_NAME
    rejection_reasons: list[str] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "strategy_name": self.strategy_name,
            "rejection_reasons": self.rejection_reasons,
            "checks_passed": self.checks_passed,
        }


def classifier_label(*, eligible: bool) -> str:
    """Gamma Trampoline™ only when the earnings gates pass. Otherwise a double calendar."""
    return GAMMA_TRAMPOLINE_NAME if eligible else DOUBLE_CALENDAR_NAME


def _as_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number > 3.0:
        number = number / 100.0
    if number <= 0:
        return None
    return number


def check_apex_strategy_eligibility(inp: ApexStrategyInput) -> ApexStrategyEligibility:
    """Earnings gates for Gamma Trampoline™. A miss names that gate and the value.

    Premium offset is measured and shown. It is not a gate. A missing earnings
    date or a missing 8-report history fails closed. Nothing is invented.
    """
    passed: list[str] = []
    rejected: list[str] = []
    days_min = gamma_earnings_days_min()
    days_max = gamma_earnings_days_max()
    if not inp.earnings_date_confirmed or inp.catalyst_days is None:
        rejected.append("Earnings date is missing.")
    elif not (days_min <= int(inp.catalyst_days) <= days_max):
        rejected.append(
            f"Calendar days to confirmed earnings {int(inp.catalyst_days)} is outside {days_min} to {days_max}."
        )
    else:
        passed.append(f"Catalyst window {int(inp.catalyst_days)} calendar days is inside {days_min} to {days_max}")

    rank_min = gamma_front_iv_rank_min()
    if inp.front_ivr is None:
        rejected.append(f"Front-week IV rank is missing, so the {rank_min:g} minimum cannot pass.")
    elif float(inp.front_ivr) <= rank_min:
        rejected.append(f"Front-week IV rank {float(inp.front_ivr):g} is not above {rank_min:g}.")
    else:
        passed.append(f"Front-week IVR {float(inp.front_ivr):g} is above {rank_min:g}")

    ratio_min = gamma_front_back_iv_ratio_min()
    front = _as_fraction(inp.front_iv)
    back = _as_fraction(inp.back_iv)
    if front is None or back is None:
        rejected.append("Front-week IV divided by back-week IV is missing, so the 1.25 minimum cannot pass.")
    else:
        ratio = front / back
        if ratio < ratio_min:
            rejected.append(f"Front-week IV divided by back-week IV is {ratio:.2f}, below {ratio_min:g}.")
        else:
            passed.append(f"Front-week IV / back-week IV is {ratio:.2f}")

    lookback = gamma_history_lookback()
    hits_min = gamma_history_hits_min()
    if inp.earnings_history_count is None or inp.earnings_history_hits is None:
        rejected.append("Earnings move history is missing; the last 8 reports are not in the data.")
    elif int(inp.earnings_history_count) < lookback or int(inp.earnings_history_hits) < hits_min:
        rejected.append(
            f"Only {int(inp.earnings_history_hits)} of the last {int(inp.earnings_history_count)} earnings moves "
            f"were smaller than the implied move; at least {hits_min} of {lookback} are required."
        )
    else:
        passed.append(
            f"{int(inp.earnings_history_hits)} of the last {int(inp.earnings_history_count)} earnings moves "
            "were smaller than the implied move"
        )

    adv_min = gamma_adv_min()
    if inp.adv is None:
        rejected.append(f"ADV is missing, so the {adv_min:,.0f} share minimum cannot pass.")
    elif float(inp.adv) <= adv_min:
        rejected.append(f"ADV {float(inp.adv):,.0f} is not above {adv_min:,.0f} shares.")
    else:
        passed.append(f"ADV {float(inp.adv):,.0f} is above {adv_min:,.0f} shares")

    oi_min = gamma_open_interest_min()
    if inp.open_interest is None:
        rejected.append(f"Open interest is missing, so the {oi_min} minimum on each strike cannot pass.")
    elif int(inp.open_interest) <= oi_min:
        rejected.append(f"Open interest {int(inp.open_interest)} is not above {oi_min}.")
    else:
        passed.append(f"Open interest {int(inp.open_interest)} is above {oi_min}")

    spread_cap = gamma_spread_max() * 100.0
    if inp.spread_pct is None:
        rejected.append(f"Bid/ask spread is missing, so the {gamma_spread_max() * 100:.0f}% of mid cap cannot pass.")
    elif float(inp.spread_pct) >= spread_cap:
        rejected.append(
            f"Bid/ask spread is {float(inp.spread_pct):.1f}% of mid, not below {gamma_spread_max() * 100:.0f}%."
        )
    else:
        passed.append(f"Spread {float(inp.spread_pct):.1f}% of mid is below {gamma_spread_max() * 100:.0f}%")

    if not inp.four_leg_structure or not inp.front_expiry_listed or not inp.back_expiry_listed:
        rejected.append(
            "The 4-leg structure is not listed: a front expiry after earnings and a back expiry about 2 weeks later must both be on the chain."
        )
    elif not inp.legs_same_strikes:
        rejected.append("Front and back expirations must use the same strikes on each side.")
    else:
        passed.append("Front expiry after earnings and back expiry about 2 weeks later are both listed")

    return ApexStrategyEligibility(
        eligible=len(rejected) == 0,
        strategy_name=classifier_label(eligible=len(rejected) == 0),
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


def _history_from_layer(vol_layer: dict[str, Any]) -> tuple[int | None, int | None]:
    """Read a supplied earnings-move history. Never invent the eight reports."""
    raw = vol_layer.get("earnings_move_history")
    if not isinstance(raw, list) or not raw:
        return None, None
    hits = 0
    counted = 0
    for row in raw:
        if not isinstance(row, dict):
            continue
        actual = row.get("actual_move")
        implied = row.get("implied_move")
        if not isinstance(actual, (int, float)) or not isinstance(implied, (int, float)):
            continue
        if isinstance(actual, bool) or isinstance(implied, bool):
            continue
        counted += 1
        if float(actual) < float(implied):
            hits += 1
    if counted == 0:
        return None, None
    return hits, counted


def build_apex_strategy_input_from_scan(
    *,
    catalyst_days: int | None,
    vol_layer: dict[str, Any],
    chain_analysis: dict[str, Any],
    contracts: list[dict[str, Any]] | None = None,
    back_month_contracts: list[dict[str, Any]] | None = None,
    earnings_date_confirmed: bool | None = None,
    spot: float | None = None,
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

    front_f = _as_fraction(float(front_iv)) if isinstance(front_iv, (int, float)) and not isinstance(front_iv, bool) else None
    back_f = _as_fraction(float(back_iv)) if isinstance(back_iv, (int, float)) and not isinstance(back_iv, bool) else None
    inverted = front_f is not None and back_f is not None and front_f / back_f >= gamma_front_back_iv_ratio_min()

    four_leg_structure = False
    legs_same_strikes = False
    front_premium_offset_pct: float | None = None
    px = spot if isinstance(spot, (int, float)) and not isinstance(spot, bool) else chain_analysis.get("spot")
    px = float(px) if isinstance(px, (int, float)) and not isinstance(px, bool) and px > 0 else None
    if back_iv is None:
        back_iv = _atm_iv(back_rows, px)
    if front_iv is None:
        front_iv = _atm_iv(front_rows, px)

    if front_rows and back_rows:
        front_call, front_put = _expected_move_pair(front_rows, px)
        if front_call is None or front_put is None:
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
            chosen = (front_call, front_put, back_call, back_put)
            oi_values: list[int] = []
            spreads: list[float] = []
            oi_complete = True
            spread_complete = True
            for contract in chosen:
                oi = contract.get("open_interest")
                if oi is None:
                    oi_complete = False
                else:
                    oi_values.append(int(oi))
                bid, ask = contract.get("bid"), contract.get("ask")
                if bid and ask and float(ask) > 0:
                    mid = (float(bid) + float(ask)) / 2.0
                    if mid > 0:
                        spreads.append((float(ask) - float(bid)) / mid * 100.0)
                    else:
                        spread_complete = False
                else:
                    spread_complete = False
            if oi_complete and oi_values:
                min_oi = min(oi_values)
            if spread_complete and len(spreads) == 4:
                spread_pct = max(spreads)

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
        earnings_date_confirmed=bool(earnings_date_confirmed) if earnings_date_confirmed is not None else bool(catalyst_days is not None and vol_layer.get("earnings_date_confirmed")),
        earnings_history_hits=_history_from_layer(vol_layer)[0],
        earnings_history_count=_history_from_layer(vol_layer)[1],
        front_expiry_listed=four_leg_structure,
        back_expiry_listed=four_leg_structure,
    )


def _atm_iv(contracts: list[dict[str, Any]], spot: float | None) -> float | None:
    """Listed call IV nearest the spot. Missing IV stays missing."""
    if spot is None:
        return None
    priced = [
        row
        for row in contracts
        if row.get("side") == "call"
        and isinstance(row.get("strike"), (int, float))
        and not isinstance(row.get("strike"), bool)
        and isinstance(row.get("iv"), (int, float))
        and not isinstance(row.get("iv"), bool)
        and float(row["iv"]) > 0
    ]
    if not priced:
        return None
    nearest = min(priced, key=lambda row: abs(float(row["strike"]) - float(spot)))
    return float(nearest["iv"])


def _expected_move_pair(
    contracts: list[dict[str, Any]],
    spot: float | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Strike A and Strike B at the front-week ATM straddle, rounded to listed strikes."""
    if spot is None:
        return None, None
    calls = [c for c in contracts if c.get("side") == "call" and c.get("strike") is not None]
    if not calls:
        return None, None
    atm_call = min(calls, key=lambda c: abs(float(c["strike"]) - spot))
    atm_put = _contract_at_strike(contracts, "put", float(atm_call["strike"]))
    call_mid = _contract_mid(atm_call)
    put_mid = _contract_mid(atm_put)
    if call_mid is None or put_mid is None:
        return None, None
    move = call_mid + put_mid
    above = _nearest_listed(contracts, "call", spot + move)
    below = _nearest_listed(contracts, "put", spot - move)
    return above, below


def _nearest_listed(contracts: list[dict[str, Any]], side: str, target: float) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike") is not None]
    if not pool:
        return None
    return min(pool, key=lambda c: (abs(float(c["strike"]) - target), float(c["strike"])))
