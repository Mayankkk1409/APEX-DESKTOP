"""Payoff calculators for all APEX encyclopedia strategy families."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from app.strategies.payoffs.helpers import (
    calendar_pnl_at_front_expiry,
    find_breakeven_range,
    find_breakeven_roots,
    intrinsic,
    leg_pnl,
    multi_leg_payoff_at_expiry,
    scan_multi_leg_payoff,
    scan_payoff,
)

Side = Literal["call", "put"]


def _positive_loss(value: float) -> float:
    return round(abs(min(0.0, value)), 2)


def _iv_assumption_note(back_iv: float) -> str:
    shown = back_iv * 100.0 if back_iv <= 3.0 else back_iv
    return (
        f"Back-leg IV {shown:.1f}% is held to front expiry."
    )


def _front_expiry_scan(
    pnl_fn: Any,
    *,
    spot: float,
    steps: int = 400,
) -> tuple[float, float, list[float], list[dict[str, float]]]:
    """Price grid from 60% to 140% of spot, about 400 points. Returns min pnl, max pnl, roots, grid."""
    span = max(spot * 0.40, 1.0)
    lo = max(spot - span, 0.01)
    hi = spot + span
    step = (hi - lo) / steps
    points: list[tuple[float, float]] = []
    grid: list[dict[str, float]] = []
    for i in range(steps + 1):
        underlying = lo + step * i
        pnl = float(pnl_fn(underlying))
        points.append((underlying, pnl))
        if i % max(steps // 40, 1) == 0 or i == steps:
            grid.append({"underlying": round(underlying, 2), "pnl": round(pnl, 2)})
    min_pnl = min(p for _, p in points)
    max_pnl = max(p for _, p in points)
    roots: list[float] = []
    for i in range(len(points) - 1):
        s0, p0 = points[i]
        s1, p1 = points[i + 1]
        if p0 == 0 or (p0 < 0 < p1) or (p1 < 0 < p0):
            denom = abs(p0) + abs(p1)
            t = 0.0 if denom == 0 else abs(p0) / denom
            roots.append(round(s0 + t * (s1 - s0), 2))
        elif abs(p0) <= 0.5:
            roots.append(round(s0, 2))
    deduped: list[float] = []
    for root in roots:
        if not deduped or abs(root - deduped[-1]) > 0.05:
            deduped.append(root)
    return min_pnl, max_pnl, deduped, grid


def calendar_spread_payoff(
    *,
    spot: float,
    strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    iv: float,
    side: Side,
    contract_multiplier: int = 100,
    short_strike: float | None = None,
    back_iv: float | None = None,
    long_front: bool = False,
) -> dict[str, Any]:
    """Numeric value at front expiry. The nearer leg is intrinsic. The later leg is Black-Scholes."""
    from app.analysis import black_scholes as bs

    long_strike = float(strike)
    short_k = float(short_strike) if short_strike is not None else long_strike
    remaining = max(int(back_dte_days) - int(front_dte_days), 1)
    years = bs.year_fraction(remaining)
    base_iv = float(back_iv if back_iv is not None else iv)
    if base_iv > 3.0:
        base_iv = base_iv / 100.0
    base_iv = max(base_iv, 0.01)

    def pnl_at(underlying: float, *, iv_scale: float) -> float:
        short_intr = intrinsic(side, short_k, underlying)
        vol = max(base_iv * iv_scale, 0.01)
        g = bs.greeks(spot=underlying, strike=long_strike, years=years, vol=vol, side=side)
        back_value = g.price if g else 0.0
        if long_front:
            # Buy the near option, sell the later option. After the near expiry the short is uncovered.
            return (short_intr - back_value - float(net_debit)) * contract_multiplier
        return (back_value - short_intr - float(net_debit)) * contract_multiplier

    min_pnl, max_pnl, breakevens, grid = _front_expiry_scan(lambda u: pnl_at(u, iv_scale=1.0), spot=spot)
    if long_front:
        worst = min_pnl
    else:
        debit_floor = -abs(float(net_debit)) * contract_multiplier if float(net_debit) > 0 else min_pnl
        worst = min(min_pnl, debit_floor)
    return {
        "max_profit": round(max_pnl, 2),
        "max_loss": _positive_loss(worst),
        "breakevens": breakevens,
        "payoff_grid": grid,
        "max_profit_iv_assumption_dependent": True,
        "max_profit_unlimited_allowed": False,
        "payoff_notes": _iv_assumption_note(base_iv),
        "breakeven_assumption_note": _iv_assumption_note(base_iv),
    }


def double_calendar_payoff(
    *,
    spot: float,
    strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    iv: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    call = calendar_spread_payoff(
        spot=spot,
        strike=strike,
        net_debit=net_debit / 2,
        front_dte_days=front_dte_days,
        back_dte_days=back_dte_days,
        iv=iv,
        side="call",
        contract_multiplier=contract_multiplier // 2,
    )
    put = calendar_spread_payoff(
        spot=spot,
        strike=strike,
        net_debit=net_debit / 2,
        front_dte_days=front_dte_days,
        back_dte_days=back_dte_days,
        iv=iv,
        side="put",
        contract_multiplier=contract_multiplier // 2,
    )
    return {
        "max_profit": round((call["max_profit"] or 0) + (put["max_profit"] or 0), 2),
        "max_loss": round((call["max_loss"] or 0) + (put["max_loss"] or 0), 2),
        "breakevens": sorted(set((call.get("breakevens") or []) + (put.get("breakevens") or [])))[:2]
        or call.get("breakevens")
        or [],
        "max_profit_iv_assumption_dependent": True,
        "payoff_notes": "Double calendar combines call and put calendar payoffs; IV-dependent.",
    }


def vertical_debit_payoff(
    *,
    long_strike: float,
    short_strike: float,
    net_debit: float,
    side: Side,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    width = abs(short_strike - long_strike)
    max_loss = round(net_debit * contract_multiplier, 2)
    max_profit = round((width - net_debit) * contract_multiplier, 2)
    be = long_strike + net_debit if side == "call" else long_strike - net_debit
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def vertical_credit_payoff(
    *,
    short_strike: float,
    long_strike: float,
    net_credit: float,
    side: Side,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    width = abs(long_strike - short_strike)
    max_profit = round(net_credit * contract_multiplier, 2)
    max_loss = round((width - net_credit) * contract_multiplier, 2)
    if side == "put":
        be = short_strike - net_credit
    else:
        be = short_strike + net_credit
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def iron_condor_payoff(
    *,
    short_put_strike: float,
    long_put_strike: float,
    short_call_strike: float,
    long_call_strike: float,
    net_credit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    put_width = short_put_strike - long_put_strike
    call_width = long_call_strike - short_call_strike
    width = max(put_width, call_width)
    return {
        "max_profit": round(net_credit * contract_multiplier, 2),
        "max_loss": round((width - net_credit) * contract_multiplier, 2),
        "breakevens": [
            round(short_put_strike - net_credit, 2),
            round(short_call_strike + net_credit, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
    }


def long_iron_condor_payoff(
    *,
    short_put_strike: float,
    long_put_strike: float,
    short_call_strike: float,
    long_call_strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    put_width = long_put_strike - short_put_strike
    call_width = short_call_strike - long_call_strike
    width = max(put_width, call_width)
    return {
        "max_profit": round((width - net_debit) * contract_multiplier, 2),
        "max_loss": round(net_debit * contract_multiplier, 2),
        "breakevens": [
            round(long_put_strike + net_debit, 2),
            round(long_call_strike - net_debit, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
    }


def long_option_payoff(
    *, premium: float, strike: float, side: Side, contract_multiplier: int = 100
) -> dict[str, Any]:
    be = strike + premium if side == "call" else strike - premium
    max_profit = None if side == "call" else round((strike - premium) * contract_multiplier, 2)
    return {
        "max_profit": max_profit if side == "put" else None,
        "max_loss": round(premium * contract_multiplier, 2),
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": side == "call",
    }


def short_option_payoff(
    *, premium: float, strike: float, side: Side, contract_multiplier: int = 100
) -> dict[str, Any]:
    be = strike + premium if side == "call" else strike - premium
    max_loss = None if side == "call" else round((strike - premium) * contract_multiplier, 2)
    return {
        "max_profit": round(premium * contract_multiplier, 2),
        "max_loss": max_loss if side == "put" else None,
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": side == "call",
    }


def long_straddle_payoff(
    *, call_premium: float, put_premium: float, strike: float, contract_multiplier: int = 100
) -> dict[str, Any]:
    total = call_premium + put_premium
    return {
        "max_profit": None,
        "max_loss": round(total * contract_multiplier, 2),
        "breakevens": [round(strike - total, 2), round(strike + total, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def long_strangle_payoff(
    *,
    call_premium: float,
    put_premium: float,
    call_strike: float,
    put_strike: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    total = call_premium + put_premium
    return {
        "max_profit": None,
        "max_loss": round(total * contract_multiplier, 2),
        "breakevens": [
            round(put_strike - total, 2),
            round(call_strike + total, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def short_straddle_payoff(
    *, call_premium: float, put_premium: float, strike: float, contract_multiplier: int = 100
) -> dict[str, Any]:
    total = call_premium + put_premium
    return {
        "max_profit": round(total * contract_multiplier, 2),
        "max_loss": None,
        "breakevens": [round(strike - total, 2), round(strike + total, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
    }


def short_strangle_payoff(
    *,
    call_premium: float,
    put_premium: float,
    call_strike: float,
    put_strike: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    total = call_premium + put_premium
    return {
        "max_profit": round(total * contract_multiplier, 2),
        "max_loss": None,
        "breakevens": [
            round(put_strike - total, 2),
            round(call_strike + total, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
    }


def long_guts_payoff(
    *,
    call_premium: float,
    put_premium: float,
    call_strike: float,
    put_strike: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    total = call_premium + put_premium
    return {
        "max_profit": None,
        "max_loss": round(total * contract_multiplier, 2),
        "breakevens": [
            round(put_strike + total, 2),
            round(call_strike - total, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def strip_payoff(
    *, call_premium: float, put_premium: float, strike: float, contract_multiplier: int = 100
) -> dict[str, Any]:
    total = call_premium + 2 * put_premium
    return {
        "max_profit": None,
        "max_loss": round(total * contract_multiplier, 2),
        "breakevens": [round(strike - total / 2, 2), round(strike + total, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def strap_payoff(
    *, call_premium: float, put_premium: float, strike: float, contract_multiplier: int = 100
) -> dict[str, Any]:
    total = 2 * call_premium + put_premium
    return {
        "max_profit": None,
        "max_loss": round(total * contract_multiplier, 2),
        "breakevens": [round(strike - total, 2), round(strike + total / 2, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def butterfly_payoff(
    *,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    net_debit: float,
    side: Side,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    wing = middle_strike - lower_strike
    max_profit = round((wing - net_debit) * contract_multiplier, 2)
    max_loss = round(net_debit * contract_multiplier, 2)
    if side == "call":
        bes = [round(lower_strike + net_debit, 2), round(upper_strike - net_debit, 2)]
    else:
        bes = [round(lower_strike + net_debit, 2), round(upper_strike - net_debit, 2)]
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": bes,
        "max_profit_iv_assumption_dependent": False,
    }


def short_butterfly_payoff(
    *,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    net_credit: float,
    side: Side,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    wing = middle_strike - lower_strike
    max_profit = round(net_credit * contract_multiplier, 2)
    max_loss = round((wing - net_credit) * contract_multiplier, 2)
    bes = [round(lower_strike + net_credit, 2), round(upper_strike - net_credit, 2)]
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": bes,
        "max_profit_iv_assumption_dependent": False,
    }


def iron_butterfly_payoff(
    *,
    put_long_strike: float,
    put_short_strike: float,
    call_short_strike: float,
    call_long_strike: float,
    net_credit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    wing = put_short_strike - put_long_strike
    return {
        "max_profit": round(net_credit * contract_multiplier, 2),
        "max_loss": round((wing - net_credit) * contract_multiplier, 2),
        "breakevens": [
            round(put_short_strike - net_credit, 2),
            round(call_short_strike + net_credit, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
    }


def long_iron_butterfly_payoff(
    *,
    put_long_strike: float,
    put_short_strike: float,
    call_short_strike: float,
    call_long_strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    wing = put_short_strike - put_long_strike
    return {
        "max_profit": round((wing - net_debit) * contract_multiplier, 2),
        "max_loss": round(net_debit * contract_multiplier, 2),
        "breakevens": [
            round(put_short_strike + net_debit, 2),
            round(call_short_strike - net_debit, 2),
        ],
        "max_profit_iv_assumption_dependent": False,
    }


def condor_spread_payoff(
    *,
    k1: float,
    k2: float,
    k3: float,
    k4: float,
    net_debit: float,
    side: Side,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    lower_wing = k2 - k1
    upper_wing = k4 - k3
    wing = min(lower_wing, upper_wing)
    max_profit = round((wing - net_debit) * contract_multiplier, 2)
    max_loss = round(net_debit * contract_multiplier, 2)
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [round(k1 + net_debit, 2), round(k4 - net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def broken_wing_butterfly_payoff(
    *,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    lower_wing = middle_strike - lower_strike
    upper_wing = upper_strike - middle_strike
    max_profit = round((min(lower_wing, upper_wing) - net_debit) * contract_multiplier, 2)
    max_loss = round(net_debit * contract_multiplier, 2)
    return {
        "max_profit": max(max_profit, 0),
        "max_loss": max_loss,
        "breakevens": [round(lower_strike + net_debit, 2), round(upper_strike - net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def christmas_tree_payoff(
    *,
    long_strike: float,
    short_strike_low: float,
    short_strike_high: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    return {
        "max_profit": None,
        "max_loss": None,
        "breakevens": [],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
        "max_profit_unlimited_allowed": False,
        "payoff_notes": (
            "Buy one call and sell one call at each of two higher strikes. "
            "The extra short call makes upside loss unlimited. No single expiry max profit is shown."
        ),
    }


def ratio_spread_payoff(
    *,
    long_strike: float,
    short_strike: float,
    net_debit: float,
    long_qty: int = 1,
    short_qty: int = 2,
    side: Side = "call",
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    width = abs(short_strike - long_strike)

    def pnl(u: float) -> float:
        long_leg = leg_pnl(
            action="buy",
            side=side,
            strike=long_strike,
            premium=net_debit if long_qty == 1 and short_qty == 1 else 0,
            underlying=u,
            quantity=long_qty,
            contract_multiplier=contract_multiplier,
        )
        short_prem = 0.0 if net_debit != 0 else 0.0
        return long_leg

    legs = [
        {"action": "buy", "side": side, "strike": long_strike, "mid": 0, "quantity": long_qty},
        {"action": "sell", "side": side, "strike": short_strike, "mid": 0, "quantity": short_qty},
    ]
    net = net_debit
    legs[0]["mid"] = net if net > 0 else width * 0.4
    legs[1]["mid"] = (legs[0]["mid"] - net) / short_qty if short_qty else 0

    max_loss, max_profit, bes = scan_multi_leg_payoff(legs, spot=long_strike, contract_multiplier=contract_multiplier)
    if side == "call":
        trap_upper = short_strike + (net / max(short_qty - long_qty, 1)) if short_qty > long_qty else None
    return {
        "max_profit": round(max_profit, 2),
        "max_loss": None,
        "breakevens": bes[:2] if len(bes) >= 2 else bes,
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
        "payoff_notes": "Ratio spread has undefined upside/downside beyond breakevens; trap zone between strikes.",
    }


def backspread_payoff(
    *,
    short_strike: float,
    long_strike: float,
    net_credit: float,
    long_qty: int = 2,
    short_qty: int = 1,
    side: Side = "call",
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    legs = [
        {"action": "sell", "side": side, "strike": short_strike, "mid": net_credit, "quantity": short_qty},
        {"action": "buy", "side": side, "strike": long_strike, "mid": 0, "quantity": long_qty},
    ]
    max_loss, max_profit, bes = scan_multi_leg_payoff(legs, spot=short_strike, contract_multiplier=contract_multiplier)
    return {
        "max_profit": None,
        "max_loss": round(abs(max_loss), 2),
        "breakevens": bes[:2] if len(bes) >= 2 else bes,
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def jade_lizard_payoff(
    *,
    short_put_strike: float,
    short_call_strike: float,
    long_call_strike: float,
    net_credit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    call_width = long_call_strike - short_call_strike
    return {
        "max_profit": round(net_credit * contract_multiplier, 2),
        "max_loss": None,
        "breakevens": [round(short_put_strike - net_credit, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
        "payoff_notes": f"Upside capped at {long_call_strike}; downside undefined below put short strike.",
    }


def _cents(value: float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cents_float(value: Decimal) -> float:
    return float(_cents(value))


def covered_call_payoff(
    *,
    stock_cost: float,
    call_strike: float,
    call_premium: float,
    contract_multiplier: int = 100,
    shares: int | None = None,
) -> dict[str, Any]:
    """Max profit (K − S + C) × shares. Max loss (S − C) × shares. Breakeven S − C."""
    count = Decimal(int(shares if shares is not None else contract_multiplier))
    entry = _cents(stock_cost)
    strike = _cents(call_strike)
    premium = _cents(call_premium)
    return {
        "max_profit": _cents_float((strike - entry + premium) * count),
        "max_loss": _cents_float((entry - premium) * count),
        "breakevens": [_cents_float(entry - premium)],
        "max_profit_iv_assumption_dependent": False,
        "payoff_notes": "Stock entry is the live ask on a new buy, or the position average cost when existing shares are used.",
    }


def covered_put_payoff(
    *,
    stock_short_price: float,
    put_strike: float,
    put_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    return {
        "max_profit": round((stock_short_price + put_premium - put_strike) * contract_multiplier, 2),
        "max_loss": None,
        "breakevens": [round(stock_short_price + put_premium, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_loss_unlimited_allowed": True,
    }


def leveraged_covered_call_payoff(
    *,
    stock_cost: float,
    call_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    """Long stock + long call — combined debit is max loss at expiry."""
    max_loss = round((stock_cost + call_premium) * contract_multiplier, 2)
    be = stock_cost + call_premium
    return {
        "max_profit": None,
        "max_loss": max_loss,
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
        "payoff_notes": "Combined stock purchase and long-call premium define max loss.",
    }


def protective_put_payoff(
    *,
    stock_cost: float,
    put_strike: float,
    put_premium: float,
    contract_multiplier: int = 100,
    shares: int | None = None,
) -> dict[str, Any]:
    """Max loss (S − K + P) × shares. Breakeven S + P. Max profit is unlimited."""
    count = Decimal(int(shares if shares is not None else contract_multiplier))
    entry = _cents(stock_cost)
    strike = _cents(put_strike)
    premium = _cents(put_premium)
    return {
        "max_profit": None,
        "max_loss": _cents_float((entry - strike + premium) * count),
        "breakevens": [_cents_float(entry + premium)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def collar_payoff(
    *,
    stock_cost: float,
    put_strike: float,
    call_strike: float,
    put_premium: float,
    call_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    net_debit = put_premium - call_premium
    max_profit = round((call_strike - stock_cost - net_debit) * contract_multiplier, 2)
    max_loss = round((stock_cost - put_strike + net_debit) * contract_multiplier, 2)
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [round(stock_cost + net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def synthetic_long_payoff(
    *,
    call_strike: float,
    call_premium: float,
    put_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    net_debit = call_premium - put_premium
    return {
        "max_profit": None,
        "max_loss": None,
        "breakevens": [round(call_strike + net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
        "max_loss_unlimited_allowed": True,
    }


def synthetic_put_payoff(
    *,
    stock_short_price: float,
    call_strike: float,
    call_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    """Short stock plus a long call. Profit is capped at a stock price of zero. The call caps the upside loss."""
    max_profit = round(max(stock_short_price - call_premium, 0.0) * contract_multiplier, 2)
    flat_loss = call_strike - stock_short_price + call_premium
    max_loss = round(max(flat_loss, 0.0) * contract_multiplier, 2)
    breakeven = stock_short_price - call_premium
    breakevens = [round(breakeven, 2)] if breakeven < call_strike else [round(call_strike, 2)]
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": False,
        "max_loss_unlimited_allowed": False,
        "payoff_notes": "Synthetic put: short stock and long call. Profit stops at a stock price of zero.",
    }


def synthetic_straddle_payoff(
    *,
    stock_price: float,
    put_strike: float,
    put_premium: float,
    put_quantity: int = 2,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    """Long stock plus two long puts. Upside is unlimited. The loss at the strike is finite."""
    qty = max(int(put_quantity), 1)
    debit = put_premium * qty
    upper = stock_price + debit
    # Below the strike the slope is 1 - qty. For two puts that root is  qty*K - S - debit.
    lower = (qty * put_strike - stock_price - debit) / (qty - 1) if qty != 1 else put_strike - debit
    kink = (put_strike - stock_price) - debit
    max_loss = round(max(-kink, 0.0) * contract_multiplier, 2)
    breakevens = sorted({round(lower, 2), round(upper, 2)})
    return {
        "max_profit": None,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
        "max_loss_unlimited_allowed": False,
        "payoff_notes": "Synthetic straddle: long stock and two long puts. Upside profit is unlimited. Loss at the strike is finite.",
    }


def synthetic_short_payoff(
    *,
    call_strike: float,
    call_premium: float,
    put_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    net_credit = call_premium - put_premium
    return {
        "max_profit": None,
        "max_loss": None,
        "breakevens": [round(call_strike + net_credit, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
        "max_loss_unlimited_allowed": True,
    }


def conversion_payoff(
    *,
    strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    return {
        "max_profit": round(abs(net_debit) * contract_multiplier, 2) if net_debit < 0 else round(net_debit * contract_multiplier, 2),
        "max_loss": round(abs(net_debit) * contract_multiplier, 2),
        "breakevens": [round(strike, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def box_spread_payoff(
    *,
    lower_strike: float,
    upper_strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    width = upper_strike - lower_strike
    return {
        "max_profit": round((width - abs(net_debit)) * contract_multiplier, 2),
        "max_loss": round(abs(net_debit) * contract_multiplier, 2),
        "breakevens": [round(lower_strike + abs(net_debit), 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def risk_reversal_payoff(
    *,
    call_strike: float,
    put_strike: float,
    call_premium: float,
    put_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    net = call_premium - put_premium
    return {
        "max_profit": None,
        "max_loss": round((put_strike - put_premium + net) * contract_multiplier, 2),
        "breakevens": [round(put_strike - put_premium + net, 2), round(call_strike + net - call_premium + put_premium, 2)],
        "max_profit_iv_assumption_dependent": False,
        "max_profit_unlimited_allowed": True,
    }


def jelly_roll_payoff(
    *,
    spot: float,
    strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    iv: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    call = calendar_spread_payoff(
        spot=spot,
        strike=strike,
        net_debit=net_debit / 2,
        front_dte_days=front_dte_days,
        back_dte_days=back_dte_days,
        iv=iv,
        side="call",
        contract_multiplier=contract_multiplier // 2,
    )
    put = calendar_spread_payoff(
        spot=spot,
        strike=strike,
        net_debit=net_debit / 2,
        front_dte_days=front_dte_days,
        back_dte_days=back_dte_days,
        iv=iv,
        side="put",
        contract_multiplier=contract_multiplier // 2,
    )
    return {
        "max_profit": round((call["max_profit"] or 0) + (put["max_profit"] or 0), 2),
        "max_loss": round((call["max_loss"] or 0) + (put["max_loss"] or 0), 2),
        "breakevens": call.get("breakevens") or [],
        "max_profit_iv_assumption_dependent": True,
    }


def pmcc_payoff(
    *,
    long_strike: float,
    short_strike: float,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    width = short_strike - long_strike
    return {
        "max_profit": round((width - net_debit) * contract_multiplier, 2),
        "max_loss": round(net_debit * contract_multiplier, 2),
        "breakevens": [round(long_strike + net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
    }


def dispersion_payoff(
    *,
    net_debit: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    return {
        "max_profit": round(abs(net_debit) * 2 * contract_multiplier, 2),
        "max_loss": round(abs(net_debit) * contract_multiplier, 2),
        "breakevens": [],
        "max_profit_iv_assumption_dependent": True,
        "payoff_notes": "Dispersion trade payoff is correlation-dependent; requires index vs single-name legs.",
    }


def multi_leg_scan_payoff(
    *,
    legs: list[dict[str, Any]],
    spot: float,
    contract_multiplier: int = 100,
    unlimited_profit: bool = False,
    unlimited_loss: bool = False,
) -> dict[str, Any]:
    max_loss, max_profit, bes = scan_multi_leg_payoff(legs, spot=spot, contract_multiplier=contract_multiplier)
    result: dict[str, Any] = {
        "max_profit": None if unlimited_profit else round(max_profit, 2),
        "max_loss": None if unlimited_loss else round(max_loss, 2),
        "breakevens": bes[:2] if len(bes) >= 2 else bes,
        "max_profit_iv_assumption_dependent": False,
    }
    if unlimited_profit:
        result["max_profit_unlimited_allowed"] = True
    if unlimited_loss:
        result["max_loss_unlimited_allowed"] = True
    return result


def _fraction_vol(raw: float | None, fallback: float) -> float:
    base = float(raw if raw is not None else fallback)
    if base > 3.0:
        base = base / 100.0
    return max(base, 0.01)


def european_double_calendar_pnl(
    *,
    call_strike: float,
    put_strike: float,
    net_debit: float,
    years: float,
    vol: float,
    contract_multiplier: int,
):
    """European Black-Scholes value of the back-week strangle minus front intrinsic, less the debit.

    This app does not have an American pricer.
    """
    from app.analysis import black_scholes as bs

    def pnl_at(underlying: float) -> float:
        short_call = max(underlying - float(call_strike), 0.0)
        short_put = max(float(put_strike) - underlying, 0.0)
        call_g = bs.greeks(spot=underlying, strike=float(call_strike), years=years, vol=vol, side="call")
        put_g = bs.greeks(spot=underlying, strike=float(put_strike), years=years, vol=vol, side="put")
        back_call = call_g.price if call_g else 0.0
        back_put = put_g.price if put_g else 0.0
        return (back_call + back_put - short_call - short_put - float(net_debit)) * contract_multiplier

    return pnl_at


def event_variance_pop(*, spot: float, expected_move: float, lower: float, upper: float) -> float | None:
    """Probability of profit between the model breakevens.

    Event-variance method: the front-week at-the-money straddle mid is the expected
    move. The terminal price is lognormal with event standard deviation equal to
    that expected move divided by the spot.
    """
    import math

    if spot <= 0 or expected_move <= 0 or upper <= lower:
        return None
    sigma = expected_move / spot
    if sigma <= 0:
        return None

    def _phi(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    z_hi = math.log(max(upper, 1e-6) / spot) / sigma
    z_lo = math.log(max(lower, 1e-6) / spot) / sigma
    return max(0.0, min(1.0, _phi(z_hi) - _phi(z_lo)))


def apex_strategy_payoff(
    *,
    spot: float,
    call_strike: float,
    put_strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    iv: float,
    contract_multiplier: int = 100,
    back_call_iv: float | None = None,
    back_put_iv: float | None = None,
    post_event_iv: float | None = None,
    expected_move: float | None = None,
) -> dict[str, Any]:
    """Double calendar at front expiry under European Black-Scholes.

    There is no American pricer in this app. When ``post_event_iv`` is set, that
    is the pre-event 30-day average the back-week IV falls to. Otherwise the
    back-leg IV already on the chain is used and the note says so.
    """
    from app.analysis import black_scholes as bs

    remaining = max(int(back_dte_days) - int(front_dte_days), 1)
    years = bs.year_fraction(remaining)
    if post_event_iv is not None:
        vol = _fraction_vol(post_event_iv, iv)
        assumption = (
            f"Priced with European Black-Scholes. This app does not have an American pricer. "
            f"Post-earnings assumption: back-week IV falls to its pre-event 30-day average of {vol * 100:.1f}%."
        )
    else:
        call_vol = _fraction_vol(back_call_iv, iv)
        put_vol = _fraction_vol(back_put_iv, iv)
        vol = (call_vol + put_vol) / 2.0
        assumption = (
            "Priced with European Black-Scholes. This app does not have an American pricer. "
            "A pre-event 30-day average was not supplied, so the back-leg IV already on the chain is used. "
            + _iv_assumption_note(vol)
        )

    pnl_at = european_double_calendar_pnl(
        call_strike=call_strike,
        put_strike=put_strike,
        net_debit=net_debit,
        years=years,
        vol=vol,
        contract_multiplier=contract_multiplier,
    )
    min_pnl, max_pnl, breakevens, grid = _front_expiry_scan(pnl_at, spot=spot)
    paid = float(net_debit)
    dollar_debit = round(abs(paid) * contract_multiplier, 2) if paid > 0 else 0.0
    loss_cap = dollar_debit if paid > 0 else _positive_loss(min_pnl)
    conflict = None
    if paid > 0 and min_pnl < -(dollar_debit + 0.01):
        conflict = {
            "min_pnl": round(min_pnl, 2),
            "net_debit": dollar_debit,
            "detail": "The price grid loss exceeds the net debit.",
        }
    pop = None
    if expected_move and len(breakevens) >= 2:
        lo, hi = min(breakevens[0], breakevens[1]), max(breakevens[0], breakevens[1])
        pop = event_variance_pop(spot=spot, expected_move=float(expected_move), lower=lo, upper=hi)
    pop_note = ""
    if pop is not None:
        pop_note = (
            f" Model probability of profit {pop * 100:.1f}% by the event-variance method: "
            "the front-week at-the-money straddle is the expected move, and the terminal price is lognormal "
            "with that move as one standard deviation."
        )
    return {
        "max_profit": round(max_pnl, 2),
        "max_loss": loss_cap if paid > 0 else _positive_loss(min_pnl),
        "max_loss_basis": "net_debit" if paid > 0 else "grid",
        "breakevens": breakevens,
        "payoff_grid": grid,
        "max_profit_iv_assumption_dependent": True,
        "max_profit_unlimited_allowed": False,
        "pricing_model": "european_black_scholes",
        "post_event_iv": vol,
        "scenario_conflict": conflict,
        "probability_of_profit": None if pop is None else round(pop, 4),
        "payoff_notes": (
            "Maximum loss is the net debit when the four legs are closed together by front expiry, "
            "confirmed on the price grid. Maximum profit has no closed form; the figure is the grid "
            "maximum under the stated IV assumption. "
            + assumption
            + pop_note
        ),
        "breakeven_assumption_note": assumption,
    }


def gamma_move_table(
    *,
    spot: float,
    call_strike: float,
    put_strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    post_event_iv: float,
    expected_move: float,
    contract_multiplier: int = 100,
    scales: tuple[float, ...] = (0.5, 1.0, 1.5),
) -> dict[str, Any]:
    """Front-expiry P&L at 0, ±0.5, ±1, ±1.5, and ±2 expected moves, plus IV-crush sensitivity."""
    from app.analysis import black_scholes as bs

    remaining = max(int(back_dte_days) - int(front_dte_days), 1)
    years = bs.year_fraction(remaining)
    base = _fraction_vol(post_event_iv, post_event_iv)
    moves = (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0)
    tables: dict[str, list[dict[str, float]]] = {}
    summary: dict[str, Any] = {}
    for scale in scales:
        vol = max(base * scale, 0.01)
        pnl_at = european_double_calendar_pnl(
            call_strike=call_strike,
            put_strike=put_strike,
            net_debit=net_debit,
            years=years,
            vol=vol,
            contract_multiplier=contract_multiplier,
        )
        rows = []
        for multiple in moves:
            underlying = spot + multiple * expected_move
            rows.append({"move": multiple, "underlying": round(underlying, 4), "pnl": round(pnl_at(underlying), 2)})
        _min_pnl, max_pnl, breakevens, _grid = _front_expiry_scan(pnl_at, spot=spot)
        key = f"{scale:.2f}"
        tables[key] = rows
        summary[key] = {
            "post_event_iv": vol,
            "max_profit": round(max_pnl, 2),
            "breakevens": breakevens,
            "min_pnl": round(_min_pnl, 2),
        }
    return {"rows": tables, "summary": summary, "pricing_model": "european_black_scholes"}


PAYOFF_FUNCTIONS: dict[str, Any] = {
    "payoff_calendar_spread": calendar_spread_payoff,
    "payoff_double_calendar": double_calendar_payoff,
    "payoff_vertical_debit": vertical_debit_payoff,
    "payoff_vertical_credit": vertical_credit_payoff,
    "payoff_iron_condor": iron_condor_payoff,
    "payoff_long_iron_condor": long_iron_condor_payoff,
    "payoff_long_option": long_option_payoff,
    "payoff_short_option": short_option_payoff,
    "payoff_long_straddle": long_straddle_payoff,
    "payoff_long_strangle": long_strangle_payoff,
    "payoff_short_straddle": short_straddle_payoff,
    "payoff_short_strangle": short_strangle_payoff,
    "payoff_long_guts": long_guts_payoff,
    "payoff_strip": strip_payoff,
    "payoff_strap": strap_payoff,
    "payoff_butterfly": butterfly_payoff,
    "payoff_short_butterfly": short_butterfly_payoff,
    "payoff_iron_butterfly": iron_butterfly_payoff,
    "payoff_long_iron_butterfly": long_iron_butterfly_payoff,
    "payoff_condor_spread": condor_spread_payoff,
    "payoff_broken_wing_butterfly": broken_wing_butterfly_payoff,
    "payoff_christmas_tree": christmas_tree_payoff,
    "payoff_ratio_spread": ratio_spread_payoff,
    "payoff_backspread": backspread_payoff,
    "payoff_jade_lizard": jade_lizard_payoff,
    "payoff_covered_call": covered_call_payoff,
    "payoff_covered_put": covered_put_payoff,
    "payoff_leveraged_covered_call": leveraged_covered_call_payoff,
    "payoff_protective_put": protective_put_payoff,
    "payoff_collar": collar_payoff,
    "payoff_synthetic_long": synthetic_long_payoff,
    "payoff_synthetic_short": synthetic_short_payoff,
    "payoff_synthetic_put": synthetic_put_payoff,
    "payoff_synthetic_straddle": synthetic_straddle_payoff,
    "payoff_conversion": conversion_payoff,
    "payoff_box_spread": box_spread_payoff,
    "payoff_risk_reversal": risk_reversal_payoff,
    "payoff_jelly_roll": jelly_roll_payoff,
    "payoff_pmcc": pmcc_payoff,
    "payoff_dispersion": dispersion_payoff,
    "payoff_multi_leg_scan": multi_leg_scan_payoff,
    "payoff_apex_strategy": apex_strategy_payoff,
}


def invoke_payoff(ref: str | None, **kwargs: Any) -> dict[str, Any]:
    if not ref:
        raise ValueError("payoff_function_ref is missing — strategy is not implemented")
    fn = PAYOFF_FUNCTIONS.get(ref)
    if fn is None:
        raise ValueError(f"Unknown payoff_function_ref: {ref}")
    return fn(**kwargs)
