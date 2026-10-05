"""APEX options-chain rule engine (Full Document §5 + §9.1).

Every threshold in :class:`RuleThresholds` is quoted from the APEX documentation and every
verdict is derived from the live values of a single contract — nothing here is templated.
When a datum is missing the gate reports ``unknown`` and the contract is downgraded to
``insufficient_data``; a missing value never silently becomes a passing zero.

Documented rules implemented here
---------------------------------
§5.1 Delta filtering      buy Delta >= 0.50, short-leg Delta <= 0.25, Delta as P(ITM) proxy
§5.2 Theta filtering      APEX Delta/Theta ratio: > 10 exceptional buy, < 3 efficient sell
§5.3 Vega assessment      Vega per 1pt IV; Vega cap in catalyst environments
§5.4 Gamma awareness      high-Gamma flag inside 7 DTE unless the structure absorbs it
§5.5 Bid/ask spread       HARD REJECT when spread > 10% of mid (configurable, 15% max)
§5.6 OI & volume gates    OI >= 500, volume > 25% of OI, UOA at volume > 3x average
§9.1 Rule 1 / Rule 2      Delta >= 0.55 with Theta < 0.05 and ratio > 10; short Delta <= 0.20
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Literal, Optional, Sequence
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.analysis.gate_config import QUOTE_FRESHNESS_SECONDS
from app.contracts import QuoteMeta
from app.schemas.market import OptionContract

NY = ZoneInfo("America/New_York")
FeedName = Literal["indicative", "opra", "other"]

GateStatus = Literal["pass", "fail", "warn", "unknown"]
Verdict = Literal[
    "buy_candidate",
    "sell_candidate",
    "tradeable",
    "screened_out",
    "rejected",
    "insufficient_data",
]
Moneyness = Literal["itm", "atm", "otm", "unknown"]


@dataclass(frozen=True)
class RuleThresholds:
    """Documented numbers. Only ``spread_max_pct_of_mid`` is user-configurable (§5.5)."""

    buy_delta_min: float = 0.50
    sell_delta_max: float = 0.25
    rule1_delta_min: float = 0.55
    rule1_theta_max: float = 0.05
    rule2_delta_max: float = 0.20
    delta_theta_buy_min: float = 10.0
    delta_theta_sell_max: float = 3.0
    spread_max_pct_of_mid: float = 0.10
    spread_max_pct_illiquid: float = 0.15
    min_open_interest: int = 500
    volume_oi_min_ratio: float = 0.25
    uoa_volume_multiple: float = 3.0
    gamma_dte_flag: int = 7
    ivr_catalyst: float = 75.0
    iv_hv_rich_pts: float = 0.10

    def with_spread_cap(self, pct: float | None) -> "RuleThresholds":
        """Clamp a user-supplied cap into the documented 1%..15% band."""
        if pct is None:
            return self
        capped = min(max(float(pct), 0.01), self.spread_max_pct_illiquid)
        return replace(self, spread_max_pct_of_mid=capped)


DEFAULT_THRESHOLDS = RuleThresholds()


@dataclass(frozen=True)
class ChainContext:
    """Chain-wide facts the per-contract rules need."""

    symbol: str
    expiry: str
    dte: int
    spot: Optional[float] = None
    atm_strike: Optional[float] = None
    catalyst_environment: bool = False
    catalyst_reason: str = "no catalyst signal derivable from this chain"
    vega_cap_override: bool = False
    structure_absorbs_gamma: bool = False
    thresholds: RuleThresholds = DEFAULT_THRESHOLDS
    uoa_reference: dict[str, float] = field(default_factory=dict)
    uoa_basis: str = "no volume reference available"
    atm_iv: Optional[float] = None
    hv: Optional[float] = None
    iv_rank: Optional[float] = None


class Gate(BaseModel):
    id: str
    label: str
    status: GateStatus
    rule: str
    observed: str
    detail: str


class ContractVerdict(BaseModel):
    symbol: str
    strike: float
    side: Literal["call", "put"]
    verdict: Verdict
    hard_reject: bool = False
    moneyness: Moneyness = "unknown"
    dte: int
    mid: Optional[float] = None
    spread_abs: Optional[float] = None
    spread_pct_of_mid: Optional[float] = None
    delta_theta_ratio: Optional[float] = None
    theta_pct_of_mid: Optional[float] = None
    vega_pct_of_mid: Optional[float] = None
    gamma_delta_shift_1pct: Optional[float] = None
    volume_oi_ratio: Optional[float] = None
    itm_probability_proxy: Optional[float] = None
    breakeven: Optional[float] = None
    buy_score: Optional[float] = None
    sell_score: Optional[float] = None
    gates: list[Gate] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    reasoning: str = ""
    greeks_source: str = "unavailable"

    @property
    def failed_gate_ids(self) -> list[str]:
        return [g.id for g in self.gates if g.status == "fail"]


#: Prices and Greeks arrive as decimals that do not land exactly in binary — a 0.10 spread on
#: a 1.00 mid computes as 0.10000000000000009. Threshold comparisons carry this tolerance so a
#: contract sitting exactly on a documented boundary is graded as the docs describe it.
EPS = 1e-9


def _ge(value: float, bound: float) -> bool:
    return value >= bound - EPS


def _le(value: float, bound: float) -> bool:
    return value <= bound + EPS


def _gt(value: float, bound: float) -> bool:
    return value > bound + EPS


def _lt(value: float, bound: float) -> bool:
    return value < bound - EPS


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _num(x: float | None, digits: int = 4) -> str:
    return "unavailable" if x is None else f"{x:.{digits}f}"


def mid_price(bid: float | None, ask: float | None) -> float | None:
    """Mid of a two-sided market. ``None`` when either side is absent.

    A zero bid with a live ask is a real one-sided market, so it yields a mid; both sides
    absent (or both zero) yields ``None`` and the caller treats it as no market.
    """
    if bid is None or ask is None:
        return None
    if bid <= 0 and ask <= 0:
        return None
    if ask < bid:
        return None
    return (bid + ask) / 2.0


def spread_metrics(bid: float | None, ask: float | None) -> tuple[float | None, float | None, float | None]:
    """Return ``(mid, absolute spread, spread as a fraction of mid)``."""
    mid = mid_price(bid, ask)
    if mid is None or bid is None or ask is None:
        return None, None, None
    spread = ask - bid
    if mid <= 0:
        return mid, spread, None
    return mid, spread, spread / mid


def daily_theta_per_share(
    theta: float | None,
    *,
    mid: float | None = None,
    multiplier: int | None = 100,
) -> float | None:
    """Theta in premium points per share per calendar day.

    Rule 1 compares this number with 0.05. A reading already near 0.15–0.20 is
    left unchanged so that contract fails. A reading larger than the option mid
    cannot be per-share premium (the contract would be worth less than one day
    of decay) and is the whole-contract Greek, so it is divided by the multiplier.
    """
    if theta is None or isinstance(theta, bool):
        return None
    try:
        value = float(theta)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    scale = int(multiplier) if multiplier and int(multiplier) > 1 else 100
    if mid is not None and mid > 0 and abs(value) > mid:
        per_share = value / scale
        if abs(per_share) <= mid:
            value = per_share
    return value


def delta_theta_ratio(delta: float | None, theta: float | None) -> float | None:
    """APEX Delta/Theta ratio (§5.2): |Delta| divided by absolute daily Theta.

    ``None`` when either Greek is missing or Theta is zero (an infinite ratio is not a
    tradeable signal, it is a missing decay estimate).
    """
    if delta is None or theta is None:
        return None
    decay = abs(theta)
    if decay <= 0:
        return None
    return abs(delta) / decay


def classify_moneyness(side: str, strike: float, spot: float | None, atm_strike: float | None = None) -> Moneyness:
    if spot is None or spot <= 0:
        return "unknown"
    if atm_strike is not None and abs(strike - atm_strike) < 1e-9:
        return "atm"
    if side == "call":
        return "itm" if strike < spot else "otm"
    return "itm" if strike > spot else "otm"


def evaluate_contract(contract: OptionContract, ctx: ChainContext) -> ContractVerdict:
    """Score one contract against every documented gate."""
    t = ctx.thresholds
    gates: list[Gate] = []
    flags: list[str] = []
    reasons: list[str] = []

    mid, spread_abs, spread_pct = spread_metrics(contract.bid, contract.ask)
    abs_delta = abs(contract.delta) if contract.delta is not None else None
    theta_day = daily_theta_per_share(contract.theta, mid=mid, multiplier=contract.multiplier)
    ratio = delta_theta_ratio(contract.delta, theta_day)
    moneyness = classify_moneyness(contract.side, contract.strike, ctx.spot, ctx.atm_strike)

    # ── §5.5 bid/ask spread — the only HARD REJECT ────────────────────────────
    hard_reject = False
    if contract.bid is None or contract.ask is None:
        gates.append(
            Gate(
                id="spread",
                label="Bid/ask spread vs mid",
                status="unknown",
                rule=f"hard reject when spread > {_pct(t.spread_max_pct_of_mid)} of mid",
                observed="quote incomplete" if contract.bid is None or contract.ask is None else "n/a",
                detail=(
                    f"{'Bid' if contract.bid is None else 'Ask'} is not published for this contract, so "
                    "execution cost cannot be measured and the §5.5 gate cannot be cleared."
                ),
            )
        )
        reasons.append("no two-sided quote — spread gate cannot be evaluated")
    elif mid is None:
        hard_reject = True
        gates.append(
            Gate(
                id="spread",
                label="Bid/ask spread vs mid",
                status="fail",
                rule=f"hard reject when spread > {_pct(t.spread_max_pct_of_mid)} of mid",
                observed=f"bid {contract.bid:.2f} / ask {contract.ask:.2f} — mid is 0",
                detail=(
                    "There is no two-sided market: mid prices to zero, so spread as a percentage of mid "
                    "is undefined and any fill is pure slippage. §5.5 rejects it."
                ),
            )
        )
        reasons.append("no two-sided market (mid = 0)")
    elif spread_pct is None:
        gates.append(
            Gate(
                id="spread",
                label="Bid/ask spread vs mid",
                status="unknown",
                rule=f"hard reject when spread > {_pct(t.spread_max_pct_of_mid)} of mid",
                observed=f"mid {mid:.2f}",
                detail="Mid is not positive, so the percentage-of-mid test is undefined.",
            )
        )
    else:
        passed = _le(spread_pct, t.spread_max_pct_of_mid)
        hard_reject = not passed
        gates.append(
            Gate(
                id="spread",
                label="Bid/ask spread vs mid",
                status="pass" if passed else "fail",
                rule=f"hard reject when spread > {_pct(t.spread_max_pct_of_mid)} of mid",
                observed=f"{spread_abs:.2f} wide on a {mid:.2f} mid = {_pct(spread_pct)}",
                detail=(
                    f"Round-trip friction is {_pct(spread_pct)} of premium "
                    f"({spread_abs:.2f} on bid {contract.bid:.2f} / ask {contract.ask:.2f}). "
                    + (
                        f"Inside the {_pct(t.spread_max_pct_of_mid)} cap, so the spread is not the reason to skip this strike."
                        if passed
                        else f"Above the {_pct(t.spread_max_pct_of_mid)} cap — §5.5 hard reject. Wide spreads are the hidden cost "
                        f"that destroys edge; paying {_pct(spread_pct / 2)} of premium on entry and again on exit "
                        "requires the thesis to be right by more than the edge it is trying to capture."
                    )
                ),
            )
        )
        if passed and _gt(spread_pct, t.spread_max_pct_of_mid * 0.75):
            flags.append("spread_near_cap")
        if not passed:
            reasons.append(f"spread {_pct(spread_pct)} of mid exceeds the {_pct(t.spread_max_pct_of_mid)} cap")

    # ── §5.6 open interest ────────────────────────────────────────────────────
    oi = contract.open_interest
    if oi is None:
        gates.append(
            Gate(
                id="open_interest",
                label="Open interest",
                status="unknown",
                rule=f"minimum {t.min_open_interest} contracts per strike",
                observed="not published",
                detail="Open interest is absent from the feed, so resting depth at this strike is unknown.",
            )
        )
    else:
        ok = oi >= t.min_open_interest
        gates.append(
            Gate(
                id="open_interest",
                label="Open interest",
                status="pass" if ok else "fail",
                rule=f"minimum {t.min_open_interest} contracts per strike",
                observed=f"{oi:,} contracts",
                detail=(
                    f"{oi:,} contracts of resting interest "
                    + (
                        f"clears the {t.min_open_interest} floor, so there is a book to exit into."
                        if ok
                        else f"is {t.min_open_interest - oi:,} short of the {t.min_open_interest} floor. Thin OI means the "
                        "exit is a negotiation, not a fill, and marks can gap on a single print."
                    )
                ),
            )
        )
        if not ok:
            reasons.append(f"open interest {oi:,} below the {t.min_open_interest} minimum")

    # ── §5.6 volume vs open interest ──────────────────────────────────────────
    vol = contract.volume
    vol_oi = None
    if vol is None or oi is None:
        gates.append(
            Gate(
                id="volume_oi",
                label="Volume vs open interest",
                status="unknown",
                rule=f"volume must exceed {_pct(t.volume_oi_min_ratio)} of open interest on the trade day",
                observed="volume or open interest not published",
                detail="Turnover against resting interest cannot be measured without both numbers.",
            )
        )
    elif oi <= 0:
        gates.append(
            Gate(
                id="volume_oi",
                label="Volume vs open interest",
                status="fail",
                rule=f"volume must exceed {_pct(t.volume_oi_min_ratio)} of open interest on the trade day",
                observed=f"volume {vol:,} against zero open interest",
                detail=(
                    "Open interest is zero at this strike, so there is no resting book at all. Whatever traded "
                    "today is opening flow into an empty strike — the §5.6 turnover test has no denominator."
                ),
            )
        )
        reasons.append("zero open interest at this strike")
    else:
        vol_oi = vol / oi
        ok = _gt(vol_oi, t.volume_oi_min_ratio)
        gates.append(
            Gate(
                id="volume_oi",
                label="Volume vs open interest",
                status="pass" if ok else "fail",
                rule=f"volume must exceed {_pct(t.volume_oi_min_ratio)} of open interest on the trade day",
                observed=f"{vol:,} traded vs {oi:,} open = {_pct(vol_oi)} turnover",
                detail=(
                    f"Today's {vol:,} contracts turn over {_pct(vol_oi)} of the {oi:,} resting. "
                    + (
                        f"Above the {_pct(t.volume_oi_min_ratio)} threshold — the strike is actually being traded today, "
                        "not merely carrying stale interest."
                        if ok
                        else f"Below the {_pct(t.volume_oi_min_ratio)} threshold, so the open interest is stale: the book exists "
                        "on paper but is not being worked today, and a resting order may not print."
                    )
                ),
            )
        )
        if not ok:
            reasons.append(f"turnover {_pct(vol_oi)} below the {_pct(t.volume_oi_min_ratio)} volume/OI gate")

    # ── §5.6 unusual options activity ─────────────────────────────────────────
    reference = ctx.uoa_reference.get(contract.side)
    if vol is None or not reference:
        gates.append(
            Gate(
                id="uoa",
                label="Unusual options activity",
                status="unknown",
                rule=f"flag when volume > {t.uoa_volume_multiple:g}x average daily volume",
                observed="no volume reference",
                detail=f"UOA needs both today's volume and a baseline. Baseline: {ctx.uoa_basis}.",
            )
        )
    else:
        multiple = vol / reference
        is_uoa = _ge(multiple, t.uoa_volume_multiple)
        if is_uoa:
            flags.append("uoa")
        gates.append(
            Gate(
                id="uoa",
                label="Unusual options activity",
                status="warn" if is_uoa else "pass",
                rule=f"flag when volume > {t.uoa_volume_multiple:g}x average daily volume",
                observed=f"{vol:,} = {multiple:.2f}x baseline {reference:,.0f}",
                detail=(
                    (
                        f"UNUSUAL ACTIVITY: {vol:,} contracts is {multiple:.2f}x the baseline of {reference:,.0f}. "
                        "Size that far above normal is positioning, not noise — read it alongside which side of the "
                        "market it printed on before fading it."
                        if is_uoa
                        else f"{multiple:.2f}x the baseline of {reference:,.0f} — normal participation, no UOA claim."
                    )
                    + f" Baseline used: {ctx.uoa_basis}."
                ),
            )
        )

    # ── §5.1 Delta ────────────────────────────────────────────────────────────
    if abs_delta is None:
        gates.append(
            Gate(
                id="delta",
                label="Delta filter",
                status="unknown",
                rule=f"buy Delta >= {t.buy_delta_min:.2f}; short-leg Delta <= {t.sell_delta_max:.2f}",
                observed="Delta not available",
                detail="Without Delta there is no directional-leverage or probability read for this strike.",
            )
        )
        reasons.append("Delta unavailable")
    else:
        buy_ok = _ge(abs_delta, t.buy_delta_min)
        sell_ok = _le(abs_delta, t.sell_delta_max)
        gates.append(
            Gate(
                id="delta",
                label="Delta filter",
                status="pass" if (buy_ok or sell_ok) else "warn",
                rule=f"buy Delta >= {t.buy_delta_min:.2f}; short-leg Delta <= {t.sell_delta_max:.2f}",
                observed=f"Delta {contract.delta:+.4f} (|Delta| {abs_delta:.4f})",
                detail=(
                    f"|Delta| {abs_delta:.4f} means roughly {abs_delta * 100:.1f}% of the underlying's next $1 move "
                    f"passes into this premium, and Delta as a probability proxy puts the odds of finishing ITM near "
                    f"{abs_delta * 100:.0f}%. "
                    + (
                        f"At or above the {t.buy_delta_min:.2f} buy floor — this is the directional-leverage bucket."
                        if buy_ok
                        else f"At or below the {t.sell_delta_max:.2f} short-leg ceiling — a {abs_delta * 100:.0f}% chance of "
                        f"finishing ITM is the high-probability premium-collection bucket."
                        if sell_ok
                        else f"Between {t.sell_delta_max:.2f} and {t.buy_delta_min:.2f}: too little leverage to buy and too "
                        "much assignment risk to sell. This is the no-man's-land the Delta filter exists to remove."
                    )
                ),
            )
        )
        if not buy_ok and not sell_ok:
            reasons.append(f"|Delta| {abs_delta:.2f} sits between the buy and sell Delta bands")

    # ── §5.2 Theta and the APEX Delta/Theta ratio ─────────────────────────────
    theta_pct = None
    if theta_day is not None and mid and mid > 0:
        theta_pct = abs(theta_day) / mid
    if ratio is None:
        gates.append(
            Gate(
                id="delta_theta",
                label="APEX Delta/Theta ratio",
                status="unknown",
                rule=f"> {t.delta_theta_buy_min:g} exceptional buying value; < {t.delta_theta_sell_max:g} efficient selling candidate",
                observed=f"Delta {_num(contract.delta)} / Theta {_num(theta_day)}",
                detail="The ratio needs both a Delta and a non-zero daily Theta; one of them is missing here.",
            )
        )
    else:
        if _gt(ratio, t.delta_theta_buy_min):
            status: GateStatus = "pass"
            verdictish = (
                f"Above {t.delta_theta_buy_min:g} — exceptional buying value. Each unit of daily decay is buying "
                f"{ratio:.1f} units of directional exposure, so the position is paid for movement rather than for waiting."
            )
        elif _lt(ratio, t.delta_theta_sell_max):
            status = "pass"
            verdictish = (
                f"Below {t.delta_theta_sell_max:g} — efficient selling candidate. Decay dominates the directional "
                "payoff, which is exactly the trade a premium seller wants to be on the other side of."
            )
        else:
            status = "warn"
            verdictish = (
                f"Between {t.delta_theta_sell_max:g} and {t.delta_theta_buy_min:g} — neither an exceptional buy nor an "
                "efficient sell. The strike is fairly priced for time, so there is no documented edge either way."
            )
        gates.append(
            Gate(
                id="delta_theta",
                label="APEX Delta/Theta ratio",
                status=status,
                rule=f"> {t.delta_theta_buy_min:g} exceptional buying value; < {t.delta_theta_sell_max:g} efficient selling candidate",
                observed=f"ratio {ratio:.2f} (|Delta| {abs_delta:.4f} / |Theta| {abs(theta_day):.4f}/day)",
                detail=(
                    f"|Delta| {abs_delta:.4f} against {abs(theta_day):.4f} of premium lost per calendar day gives a ratio of {ratio:.2f}. "
                    + (
                        f"That decay is {_pct(theta_pct)} of the {mid:.2f} mid per day, so the position bleeds its whole premium in "
                        f"about {1 / theta_pct:.0f} days if the underlying never moves. "
                        if theta_pct
                        else ""
                    )
                    + verdictish
                ),
            )
        )

    # §9.1 Rule 1 / Rule 2 — the tighter proprietary filters
    if abs_delta is not None and theta_day is not None:
        from app.analysis.gate_config import iv_below_hv, rule1_theta_failures

        theta_fail, theta_notes = rule1_theta_failures(
            delta=abs_delta,
            theta_per_share=theta_day,
            premium=mid,
        )
        spread_ok = spread_pct is not None and spread_pct < 0.08
        iv_ok = iv_below_hv(contract.iv, ctx.hv) is True
        if not theta_fail and spread_ok and iv_ok:
            flags.append("rule1_buy")
        elif any("skipped" in note for note in theta_notes):
            flags.append("rule1_ratio_skipped")
        if _le(abs_delta, t.rule2_delta_max) and spread_pct is not None and _le(spread_pct, t.spread_max_pct_of_mid):
            flags.append("rule2_sell")

    # ── §5.3 Vega and the Vega cap ────────────────────────────────────────────
    vega_pct = None
    if contract.vega is not None and mid and mid > 0:
        vega_pct = contract.vega / mid
    if contract.vega is None:
        gates.append(
            Gate(
                id="vega_cap",
                label="Vega cap",
                status="unknown",
                rule="long Vega in a catalyst environment requires explicit override or APEX Strategy structure",
                observed="Vega not available",
                detail="IV-crush exposure cannot be sized without Vega.",
            )
        )
    elif not ctx.catalyst_environment:
        gates.append(
            Gate(
                id="vega_cap",
                label="Vega cap",
                status="pass",
                rule="long Vega in a catalyst environment requires explicit override or APEX Strategy structure",
                observed=f"Vega {contract.vega:.4f} per IV point; cap inactive",
                detail=(
                    f"A 1-point IV move is worth {contract.vega:.4f} of premium"
                    + (f" ({_pct(vega_pct)} of the {mid:.2f} mid)" if vega_pct else "")
                    + f". The Vega cap is not armed because {ctx.catalyst_reason}, so long Vega here is an ordinary "
                    "volatility exposure rather than a documented event risk."
                ),
            )
        )
    else:
        satisfied = ctx.vega_cap_override or ctx.structure_absorbs_gamma
        if not satisfied:
            flags.append("vega_cap_blocked")
        gates.append(
            Gate(
                id="vega_cap",
                label="Vega cap",
                status="pass" if satisfied else "fail",
                rule="long Vega in a catalyst environment requires explicit override or APEX Strategy structure",
                observed=f"Vega {contract.vega:.4f} per IV point"
                + (f" = {_pct(vega_pct)} of mid" if vega_pct else "")
                + f"; override {'granted' if ctx.vega_cap_override else 'not granted'}"
                + (", APEX Strategy structure selected" if ctx.structure_absorbs_gamma else ""),
                detail=(
                    f"Catalyst environment detected ({ctx.catalyst_reason}). Long Vega of {contract.vega:.4f} per IV point"
                    + (
                        f" means a 10-point post-event IV crush erases about {contract.vega * 10:.2f} of premium — "
                        f"{_pct(min(vega_pct * 10, 1.0))} of the {mid:.2f} mid — even if the underlying moves the right way. "
                        if vega_pct
                        else " is exposed to a post-event IV crush. "
                    )
                    + (
                        "Override is in force, so this exposure is accepted deliberately."
                        if ctx.vega_cap_override
                        else "APEX Strategy structure absorbs the crush, so the cap is satisfied structurally."
                        if ctx.structure_absorbs_gamma
                        else "The §5.3 Vega cap therefore blocks a long-premium entry here until an explicit override is "
                        "granted or the position is expressed as a APEX Strategy. The cap constrains the long side "
                        "only: selling this contract is short Vega, so the same crush works in the seller's favour."
                    )
                ),
            )
        )

    # ── §5.4 Gamma awareness ──────────────────────────────────────────────────
    gamma_shift = None
    if contract.gamma is not None and ctx.spot:
        gamma_shift = contract.gamma * ctx.spot * 0.01
    if contract.gamma is None:
        gates.append(
            Gate(
                id="gamma_dte",
                label="Gamma risk inside 7 DTE",
                status="unknown",
                rule=f"flag high Gamma within {t.gamma_dte_flag} days of expiration unless the structure accounts for it",
                observed="Gamma not available",
                detail="Delta acceleration cannot be measured without Gamma.",
            )
        )
    elif ctx.dte > t.gamma_dte_flag:
        gates.append(
            Gate(
                id="gamma_dte",
                label="Gamma risk inside 7 DTE",
                status="pass",
                rule=f"flag high Gamma within {t.gamma_dte_flag} days of expiration unless the structure accounts for it",
                observed=f"{ctx.dte} DTE, Gamma {contract.gamma:.4f}",
                detail=(
                    f"At {ctx.dte} days out the {t.gamma_dte_flag}-day Gamma window is not open. Delta still moves "
                    f"{contract.gamma:.4f} per $1"
                    + (f" ({gamma_shift:+.4f} per 1% move in the underlying)" if gamma_shift else "")
                    + ", but that convexity is not yet the dominant risk."
                ),
            )
        )
    else:
        absorbed = ctx.structure_absorbs_gamma
        if not absorbed:
            flags.append("gamma_risk_7dte")
        gates.append(
            Gate(
                id="gamma_dte",
                label="Gamma risk inside 7 DTE",
                status="pass" if absorbed else "warn",
                rule=f"flag high Gamma within {t.gamma_dte_flag} days of expiration unless the structure accounts for it",
                observed=f"{ctx.dte} DTE, Gamma {contract.gamma:.4f}"
                + (f", delta shift {gamma_shift:+.4f} per 1% move" if gamma_shift else ""),
                detail=(
                    f"Inside the {t.gamma_dte_flag}-day window at {ctx.dte} DTE. Gamma {contract.gamma:.4f} means Delta "
                    f"repriced by {contract.gamma:.4f} for every $1 the underlying travels"
                    + (
                        f" — a 1% move ({ctx.spot * 0.01:.2f}) shifts Delta by {gamma_shift:+.4f}, so a position that starts "
                        f"delta-neutral does not stay delta-neutral through the session. "
                        if gamma_shift
                        else ". "
                    )
                    + (
                        "The selected structure accounts for it (APEX Strategy), so the flag is satisfied."
                        if absorbed
                        else "Gamma risk is flagged: short premium here can lose faster than Theta collects, and long "
                        "premium needs the move immediately rather than eventually."
                    )
                ),
            )
        )

    # ── verdict ───────────────────────────────────────────────────────────────
    liquidity_ids = {"spread", "open_interest", "volume_oi"}
    liquidity_gates = [g for g in gates if g.id in liquidity_ids]
    liquidity_failed = [g for g in liquidity_gates if g.status == "fail"]
    liquidity_unknown = [g for g in liquidity_gates if g.status == "unknown"]

    buy_score, sell_score = _score(contract, ctx, mid, spread_pct, ratio, abs_delta, theta_pct, vega_pct)

    if hard_reject:
        verdict: Verdict = "rejected"
    elif liquidity_failed:
        verdict = "screened_out"
    elif abs_delta is None or ratio is None or liquidity_unknown:
        verdict = "insufficient_data"
    elif _ge(abs_delta, t.buy_delta_min) and _gt(ratio, t.delta_theta_buy_min) and "vega_cap_blocked" not in flags:
        verdict = "buy_candidate"
    elif _le(abs_delta, t.sell_delta_max) and _lt(ratio, t.delta_theta_sell_max):
        verdict = "sell_candidate"
    else:
        verdict = "tradeable"

    return ContractVerdict(
        symbol=contract.symbol,
        strike=contract.strike,
        side=contract.side,
        verdict=verdict,
        hard_reject=hard_reject,
        moneyness=moneyness,
        dte=ctx.dte,
        mid=mid,
        spread_abs=spread_abs,
        spread_pct_of_mid=spread_pct,
        delta_theta_ratio=ratio,
        theta_pct_of_mid=theta_pct,
        vega_pct_of_mid=vega_pct,
        gamma_delta_shift_1pct=gamma_shift,
        volume_oi_ratio=vol_oi,
        itm_probability_proxy=abs_delta,
        breakeven=_breakeven(contract, mid),
        buy_score=buy_score,
        sell_score=sell_score,
        gates=gates,
        flags=flags,
        reasons=reasons,
        reasoning=_reasoning(contract, ctx, verdict, gates, flags, reasons, mid, spread_pct, ratio, abs_delta),
        greeks_source=contract.greeks_source,
    )


def _breakeven(contract: OptionContract, mid: float | None) -> float | None:
    if mid is None:
        return None
    return contract.strike + mid if contract.side == "call" else contract.strike - mid


def _score(
    contract: OptionContract,
    ctx: ChainContext,
    mid: float | None,
    spread_pct: float | None,
    ratio: float | None,
    abs_delta: float | None,
    theta_pct: float | None,
    vega_pct: float | None,
) -> tuple[float | None, float | None]:
    """Rank candidates 0-100 within their own bucket. ``None`` when inputs are too thin."""
    t = ctx.thresholds
    if abs_delta is None or ratio is None or mid is None or spread_pct is None:
        return None, None

    buy = 0.0
    buy += min(ratio / t.delta_theta_buy_min, 2.0) * 30.0
    buy += min(abs_delta / t.buy_delta_min, 1.5) * 25.0
    buy += max(0.0, 1.0 - spread_pct / t.spread_max_pct_of_mid) * 20.0
    if theta_pct is not None:
        buy += max(0.0, 1.0 - theta_pct / 0.10) * 15.0
    if ctx.catalyst_environment and vega_pct is not None:
        buy -= min(vega_pct * 100.0, 20.0)
    if ctx.dte <= t.gamma_dte_flag and not ctx.structure_absorbs_gamma:
        buy -= 10.0

    sell = 0.0
    sell += max(0.0, 1.0 - ratio / t.delta_theta_buy_min) * 30.0
    sell += max(0.0, 1.0 - abs_delta / t.buy_delta_min) * 25.0
    sell += max(0.0, 1.0 - spread_pct / t.spread_max_pct_of_mid) * 20.0
    if theta_pct is not None:
        sell += min(theta_pct / 0.05, 1.0) * 15.0
    if contract.iv is not None and ctx.atm_iv:
        sell += min(max(contract.iv / ctx.atm_iv - 1.0, 0.0) * 40.0, 10.0)
    if ctx.dte <= t.gamma_dte_flag and not ctx.structure_absorbs_gamma:
        sell -= 12.0

    return round(max(0.0, min(100.0, buy)), 1), round(max(0.0, min(100.0, sell)), 1)


def _reasoning(
    contract: OptionContract,
    ctx: ChainContext,
    verdict: Verdict,
    gates: list[Gate],
    flags: list[str],
    reasons: list[str],
    mid: float | None,
    spread_pct: float | None,
    ratio: float | None,
    abs_delta: float | None,
) -> str:
    """Assemble the verdict sentence from the gate results that actually fired."""
    label = f"{contract.symbol} — {ctx.symbol} {ctx.expiry} {contract.strike:g} {contract.side}"
    quote = (
        f"bid {contract.bid:.2f} / ask {contract.ask:.2f} (mid {mid:.2f}"
        + (f", {_pct(spread_pct)} wide" if spread_pct is not None else "")
        + ")"
        if contract.bid is not None and contract.ask is not None and mid is not None
        else "no complete two-sided quote"
    )
    greek_note = {
        "vendor": "Greeks are vendor-published",
        "model": "Greeks are locally computed Black-Scholes, not vendor-published",
        "unavailable": "Greeks are unavailable",
    }[contract.greeks_source]

    head = {
        "rejected": "HARD REJECT under §5.5.",
        "screened_out": "Screened out by the §5.6 liquidity gates.",
        "buy_candidate": "Qualifies as a buy candidate under §5.1 and §5.2.",
        "sell_candidate": "Qualifies as a short-leg candidate under §5.1 and §5.2.",
        "tradeable": "Clears every liquidity gate but does not fit a documented directional bucket.",
        "insufficient_data": "Cannot be graded — required data is missing.",
    }[verdict]

    parts = [f"{label}: {head} Quote is {quote}; {greek_note}."]
    if abs_delta is not None:
        parts.append(
            f"Delta {contract.delta:+.4f} implies roughly a {abs_delta * 100:.0f}% chance of finishing ITM"
            + (f" and pairs with a Delta/Theta ratio of {ratio:.2f}." if ratio is not None else " but the Delta/Theta ratio is unavailable.")
        )
    if reasons:
        parts.append("Blocking findings: " + "; ".join(reasons) + ".")
    fired = [g for g in gates if g.status in {"fail", "warn"}]
    if fired:
        parts.append(" ".join(g.detail for g in fired))
    if "uoa" in flags:
        parts.append("Unusual options activity is present on this strike.")
    if "rule1_buy" in flags:
        from app.analysis.gate_config import theta_filter_mode

        if theta_filter_mode() == "abs_per_share":
            parts.append(
                f"Meets §9.1 Rule 1 (Delta >= {ctx.thresholds.rule1_delta_min:.2f}, daily Theta < "
                f"{ctx.thresholds.rule1_theta_max:.2f}, Delta/Theta > {ctx.thresholds.delta_theta_buy_min:g}, "
                "spread under 8% of mid, IV below HV)."
            )
        else:
            parts.append(
                "Meets §9.1 Rule 1 (Delta >= 0.55, theta within the percent-of-premium cap, "
                "spread under 8% of mid, IV below HV). The delta/theta ratio was skipped."
            )
    if "rule2_sell" in flags:
        parts.append(
            f"Meets §9.1 Rule 2 short-leg profile (Delta <= {ctx.thresholds.rule2_delta_max:.2f} with a spread inside the cap)."
        )
    return " ".join(parts)


def evaluate_chain(contracts: Iterable[OptionContract], ctx: ChainContext) -> list[ContractVerdict]:
    return [evaluate_contract(c, ctx) for c in contracts]


def clears_oi_and_volume(
    open_interest: int | None,
    volume: int | None,
    thresholds: RuleThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """Same §5.6 numbers the per-contract gates use. Does not change those numbers."""
    if open_interest is None or volume is None:
        return False
    if open_interest < thresholds.min_open_interest or open_interest <= 0:
        return False
    return _gt(volume / open_interest, thresholds.volume_oi_min_ratio)


def contract_clears_oi_and_volume(
    contract: OptionContract | dict[str, Any],
    thresholds: RuleThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    if isinstance(contract, OptionContract):
        return clears_oi_and_volume(contract.open_interest, contract.volume, thresholds)
    oi = contract.get("open_interest")
    vol = contract.get("volume")
    oi_i = int(oi) if isinstance(oi, (int, float)) and not isinstance(oi, bool) else None
    vol_i = int(vol) if isinstance(vol, (int, float)) and not isinstance(vol, bool) else None
    return clears_oi_and_volume(oi_i, vol_i, thresholds)


def weekday_sessions(anchor: date, *, back: int = 14, forward: int = 1) -> list[tuple[datetime, datetime]]:
    """Regular NYSE hours on weekdays. Holidays are not in this fallback."""
    sessions: list[tuple[datetime, datetime]] = []
    for offset in range(-back, forward + 1):
        day = anchor + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        sessions.append(
            (
                datetime.combine(day, time(9, 30), tzinfo=NY),
                datetime.combine(day, time(16, 0), tzinfo=NY),
            )
        )
    return sessions


def parse_alpaca_calendar(rows: Sequence[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    """Regular-hours sessions from Alpaca ``GET /v2/calendar`` (open/close, not the extended session)."""
    sessions: list[tuple[datetime, datetime]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            continue
        try:
            day = date.fromisoformat(str(row["date"])[:10])
            open_h, open_m = (int(part) for part in str(row.get("open") or "09:30").split(":")[:2])
            close_h, close_m = (int(part) for part in str(row.get("close") or "16:00").split(":")[:2])
        except (TypeError, ValueError):
            continue
        sessions.append(
            (
                datetime.combine(day, time(open_h, open_m), tzinfo=NY),
                datetime.combine(day, time(close_h, close_m), tzinfo=NY),
            )
        )
    return sessions


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_quoted_at(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def in_regular_session(now: datetime, sessions: Sequence[tuple[datetime, datetime]]) -> bool:
    clock = _aware(now)
    return any(_aware(start) <= clock < _aware(end) for start, end in sessions)


def classify_quote_freshness(
    *,
    quoted_at: datetime | str | None,
    now: datetime,
    sessions: Sequence[tuple[datetime, datetime]] | None = None,
    feed_delayed: bool = False,
    freshness_seconds: int = QUOTE_FRESHNESS_SECONDS,
) -> tuple[bool, str | None]:
    """Market-hours staleness. The age cap stays ``QUOTE_FRESHNESS_SECONDS``.

    Outside a regular session the quote is last close and is not failed for age.
    A delayed feed is labeled ``delayed``. During the session an age past the cap
    is still stale.
    """
    clock = _aware(now)
    if sessions is None:
        sessions = weekday_sessions(clock.astimezone(NY).date())
    if not in_regular_session(clock, sessions):
        return False, "last_close"
    quoted = _parse_quoted_at(quoted_at)
    if quoted is None:
        return (False, "delayed") if feed_delayed else (False, None)
    age = (clock - quoted).total_seconds()
    if age > freshness_seconds:
        return True, "delayed" if feed_delayed else "stale"
    if feed_delayed:
        return False, "delayed"
    return False, None


def canonical_feed(feed: str | None, *, delayed: bool | None = None) -> tuple[FeedName, bool]:
    """Map a vendor feed name onto the frozen ``indicative | opra | other`` set.

    Alpaca's indicative options feed is delayed (trades by 15 minutes; quotes are
    not OPRA). OPRA is the subscribed consolidated feed and is not labeled delayed.
    """
    name = (feed or "").strip().lower()
    if name == "indicative":
        return "indicative", True if delayed is None else delayed
    if name == "opra":
        return "opra", False if delayed is None else delayed
    return "other", bool(delayed)


def build_quote_meta(
    *,
    provider: str,
    feed: str,
    quoted_at: str | datetime | None,
    received_at: str | datetime | None,
    bid: float | None,
    ask: float | None,
    bid_size: float | None,
    ask_size: float | None,
    now: datetime | None = None,
    sessions: Sequence[tuple[datetime, datetime]] | None = None,
    feed_delayed: bool | None = None,
) -> dict[str, Any]:
    """QuoteMeta dict. Field names match the frozen contract."""
    feed_name, delayed = canonical_feed(feed, delayed=feed_delayed)
    clock = _aware(now or datetime.now(timezone.utc))
    is_stale, reason = classify_quote_freshness(
        quoted_at=quoted_at,
        now=clock,
        sessions=sessions,
        feed_delayed=delayed,
    )
    quoted_text = quoted_at.isoformat() if isinstance(quoted_at, datetime) else (str(quoted_at) if quoted_at else None)
    received_text = (
        received_at.isoformat() if isinstance(received_at, datetime) else (str(received_at) if received_at else clock.isoformat())
    )
    meta = QuoteMeta(
        provider=provider,
        feed=feed_name,
        quotedAt=quoted_text,
        receivedAt=received_text,
        bid=bid,
        ask=ask,
        bidSize=None if bid_size is None else float(bid_size),
        askSize=None if ask_size is None else float(ask_size),
        isStale=is_stale,
        staleReason=reason,
    )
    return asdict(meta)


def chain_quote_flags(
    contracts: Sequence[OptionContract],
    *,
    atm_iv: float | None,
    spot: float | None,
    feed: str | None,
    source: str | None,
    timestamp: str | None,
) -> list[dict[str, Any]]:
    """Flags 2B can ledger. Inverted put skew, crossed markets, IV outside the chain range."""
    flags: list[dict[str, Any]] = []
    common = {"feed": feed, "source": source or "unavailable", "timestamp": timestamp}

    if atm_iv is not None and spot is not None and spot > 0:
        otm_puts = [
            c
            for c in contracts
            if c.side == "put" and c.strike < spot and c.iv is not None and c.iv > 0
        ]
        if otm_puts:
            nearest = max(otm_puts, key=lambda c: c.strike)
            if nearest.iv is not None and nearest.iv < atm_iv:
                flags.append(
                    {
                        "code": "inverted_put_skew",
                        "symbol": nearest.symbol,
                        "strike": nearest.strike,
                        "value": nearest.iv,
                        "threshold": atm_iv,
                        "detail": (
                            f"OTM put {nearest.strike:g} IV {nearest.iv:.4f} is below ATM IV {atm_iv:.4f}"
                        ),
                        **common,
                    }
                )

    for contract in contracts:
        if contract.bid is not None and contract.ask is not None and contract.bid > contract.ask:
            flags.append(
                {
                    "code": "crossed_market",
                    "symbol": contract.symbol,
                    "strike": contract.strike,
                    "side": contract.side,
                    "value": contract.bid,
                    "threshold": contract.ask,
                    "detail": f"bid {contract.bid} is greater than ask {contract.ask}",
                    **common,
                }
            )
        if contract.iv is None or contract.iv <= 0:
            continue
        others = [c.iv for c in contracts if c is not contract and c.iv is not None and c.iv > 0]
        if len(others) < 2:
            continue
        lo, hi = min(others), max(others)
        span = hi - lo
        if contract.iv < lo - span or contract.iv > hi + span:
            flags.append(
                {
                    "code": "iv_outside_chain_range",
                    "symbol": contract.symbol,
                    "strike": contract.strike,
                    "side": contract.side,
                    "value": contract.iv,
                    "threshold": [lo, hi],
                    "detail": (
                        f"IV {contract.iv:.4f} sits outside the other contracts' range "
                        f"{lo:.4f}–{hi:.4f} by more than that range's width"
                    ),
                    **common,
                }
            )
    return flags


def build_uoa_reference(contracts: Iterable[OptionContract]) -> tuple[dict[str, float], str]:
    """Baseline for the §5.6 UOA test.

    Per-contract 20-day average daily volume is not published in the options snapshot feed,
    so the baseline is the mean traded volume across the same side of this expiry. The basis
    string is surfaced verbatim in the UI — the comparison is never presented as a true ADV.
    """
    buckets: dict[str, list[int]] = {"call": [], "put": []}
    for c in contracts:
        if c.volume is not None and c.side in buckets:
            buckets[c.side].append(int(c.volume))
    ref = {side: (sum(v) / len(v)) for side, v in buckets.items() if v}
    if not ref:
        return {}, "no contract on this expiry published a traded volume, so no UOA baseline exists"
    basis = (
        "mean traded volume across the same side of this expiry ("
        + ", ".join(f"{side} {value:,.0f}" for side, value in sorted(ref.items()))
        + "); per-contract 20-day ADV is not published by the options snapshot feed"
    )
    return ref, basis
