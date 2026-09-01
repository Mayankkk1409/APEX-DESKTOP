"""Payoff calculators for all APEX encyclopedia strategy families."""

from __future__ import annotations

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
) -> dict[str, Any]:
    pnl_fn = calendar_pnl_at_front_expiry(
        spot=spot,
        strike=strike,
        net_debit=net_debit,
        front_dte_days=front_dte_days,
        back_dte_days=back_dte_days,
        iv=iv,
        side=side,
        contract_multiplier=contract_multiplier,
    )
    span = max(strike * 0.25, spot * 0.20, 5.0)
    max_loss, max_profit = scan_payoff(pnl_fn, center=strike, span=span)
    breakevens = find_breakeven_range(pnl_fn, center=strike, span=span)
    return {
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "breakevens": breakevens,
        "max_profit_iv_assumption_dependent": True,
        "payoff_notes": (
            "Calendar max profit and breakeven range assume constant IV on the back-month leg "
            "at front expiration; actual results vary with vol crush and skew."
        ),
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
    wing = k2 - k1
    body = k3 - k2
    max_profit = round((body - net_debit) * contract_multiplier, 2)
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
    width = short_strike_high - long_strike
    return {
        "max_profit": round((width - net_debit) * contract_multiplier, 2),
        "max_loss": round(net_debit * contract_multiplier, 2),
        "breakevens": [round(long_strike + net_debit, 2)],
        "max_profit_iv_assumption_dependent": False,
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


def covered_call_payoff(
    *,
    stock_cost: float,
    call_strike: float,
    call_premium: float,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    max_profit = round((call_strike - stock_cost + call_premium) * contract_multiplier, 2)
    max_loss = round((stock_cost - call_premium) * contract_multiplier, 2)
    be = stock_cost - call_premium
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": [round(be, 2)],
        "max_profit_iv_assumption_dependent": False,
        "payoff_notes": "Requires long stock at entry cost; max loss if stock goes to zero.",
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
) -> dict[str, Any]:
    max_loss = round((stock_cost - put_strike + put_premium) * contract_multiplier, 2)
    be = stock_cost + put_premium
    return {
        "max_profit": None,
        "max_loss": max_loss,
        "breakevens": [round(be, 2)],
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
) -> dict[str, Any]:
    from app.analysis import black_scholes as bs

    remaining_dte = max(back_dte_days - front_dte_days, 1)
    years_remaining = bs.year_fraction(remaining_dte)
    vol = max(iv, 0.08)
    span = max(call_strike, put_strike, spot) * 0.30
    center = spot

    def pnl_at_front_expiry(underlying: float) -> float:
        short_call_intr = max(underlying - call_strike, 0.0)
        short_put_intr = max(put_strike - underlying, 0.0)
        call_g = bs.greeks(spot=underlying, strike=call_strike, years=years_remaining, vol=vol, side="call")
        put_g = bs.greeks(spot=underlying, strike=put_strike, years=years_remaining, vol=vol, side="put")
        back_call_val = call_g.price if call_g else 0.0
        back_put_val = put_g.price if put_g else 0.0
        return (back_call_val + back_put_val - short_call_intr - short_put_intr - net_debit) * contract_multiplier

    max_loss, _ = scan_payoff(pnl_at_front_expiry, center=center, span=span)
    breakevens = find_breakeven_range(pnl_at_front_expiry, center=center, span=span)

    return {
        "max_profit": None,
        "max_loss": round(max_loss, 2),
        "breakevens": breakevens,
        "max_profit_iv_assumption_dependent": True,
        "max_profit_unlimited_allowed": True,
        "payoff_notes": (
            "APEX Strategy max loss and breakeven range assume constant IV on back-month legs at front "
            "expiration; upside is theoretically unlimited on large moves."
        ),
    }


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
