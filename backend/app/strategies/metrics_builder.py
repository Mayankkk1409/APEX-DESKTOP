"""Unified metrics builder for all 100 registry strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.strategies.chain_utils import (
    contract_at_strike,
    dte_from_expiry,
    make_option_leg,
    make_stock_leg,
    mid,
    nearest_strike_contract,
    net_debit_credit,
    normalize_leg_mids,
    next_higher_strike,
    next_lower_strike,
    pick_strike,
    resolve_contract_from_recommended,
    sorted_strikes,
)
from app.strategies.payoffs.core import PAYOFF_FUNCTIONS, invoke_payoff
from app.strategies.registry import STRATEGY_REGISTRY, StrategySpec, get_strategy_spec

Side = Literal["call", "put"]


@dataclass
class BuildContext:
    strategy_id: str
    spot: float
    contracts: list[dict[str, Any]]
    back_month_contracts: list[dict[str, Any]]
    front_expiry: str | None
    back_expiry: str | None
    iv: float
    ticker: str
    contract_multiplier: int = 100
    recommended: dict[str, Any] | None = None


def _empty_metrics(multiplier: int = 100) -> dict[str, Any]:
    return {
        "max_loss": None,
        "max_profit": None,
        "net_debit_credit": None,
        "net_type": None,
        "breakevens": [],
        "legs": [],
        "per_contract_multiplier": multiplier,
    }


def _finalize(spec: StrategySpec, legs: list[dict[str, Any]], payoff: dict[str, Any], net: float, net_type: str, mult: int) -> dict[str, Any]:
    legs = normalize_leg_mids(list(legs))
    net, net_type = net_debit_credit(legs)
    metrics = _empty_metrics(mult)
    metrics.update(payoff)
    if spec.max_profit_type == "unlimited":
        metrics["max_profit"] = None
        metrics["max_profit_unlimited_allowed"] = True
    if spec.max_loss_type == "unlimited":
        metrics["max_loss"] = None
        metrics["max_loss_unlimited_allowed"] = True
    metrics["legs"] = legs
    metrics["net_debit_credit"] = round(abs(net), 2)
    metrics["net_type"] = net_type
    metrics["per_contract_multiplier"] = mult
    if spec.risk_type == "undefined" and payoff.get("max_loss") is None:
        metrics["max_loss_unlimited_allowed"] = True
    if spec.max_profit_type == "unlimited" and payoff.get("max_profit") is None:
        metrics.setdefault("max_profit_unlimited_allowed", True)
    return metrics


def _build_single_long(ctx: BuildContext, side: Side, *, delta_target: float = 0.55) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    c = resolve_contract_from_recommended(ctx.contracts, ctx.recommended, side, ctx.spot, delta_target=delta_target)
    leg = make_option_leg("buy", c, expiry=ctx.front_expiry)
    legs = [leg] if leg else []
    prem = (leg or {}).get("mid") or 0
    strike = float((leg or {}).get("strike") or ctx.spot)
    payoff = invoke_payoff("payoff_long_option", premium=prem, strike=strike, side=side, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    return legs, _finalize(get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_call"], legs, payoff, net, nt, ctx.contract_multiplier)


def _build_single_short(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    c = pick_strike(ctx.contracts, side, ctx.spot, 0.20) or nearest_strike_contract(ctx.contracts, side, ctx.spot)
    leg = make_option_leg("sell", c, expiry=ctx.front_expiry)
    legs = [leg] if leg else []
    prem = (leg or {}).get("mid") or 0
    strike = float((leg or {}).get("strike") or ctx.spot)
    payoff = invoke_payoff("payoff_short_option", premium=prem, strike=strike, side=side, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["naked_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_vertical_debit(ctx: BuildContext, side: Side, *, wide: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    long_c = pick_strike(ctx.contracts, side, ctx.spot, 0.55) or nearest_strike_contract(ctx.contracts, side, ctx.spot)
    if not long_c:
        return [], _empty_metrics(ctx.contract_multiplier)
    ls = float(long_c["strike"])
    short_c = next_higher_strike(ctx.contracts, side, ls, wide=wide) if side == "call" else next_lower_strike(ctx.contracts, side, ls, wide=wide)
    legs = [lg for lg in [make_option_leg("buy", long_c, expiry=ctx.front_expiry), make_option_leg("sell", short_c, expiry=ctx.front_expiry)] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_vertical_debit",
        long_strike=ls,
        short_strike=float(short_c["strike"]) if short_c else ls + 5,
        net_debit=net,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["bull_call_spread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_vertical_credit(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_c = pick_strike(ctx.contracts, side, ctx.spot, 0.20) or nearest_strike_contract(ctx.contracts, side, ctx.spot)
    if not short_c:
        return [], _empty_metrics(ctx.contract_multiplier)
    ss = float(short_c["strike"])
    long_c = next_lower_strike(ctx.contracts, side, ss) if side == "put" else next_higher_strike(ctx.contracts, side, ss)
    legs = [lg for lg in [make_option_leg("sell", short_c, expiry=ctx.front_expiry), make_option_leg("buy", long_c, expiry=ctx.front_expiry)] if lg]
    net, nt = net_debit_credit(legs)
    credit = -net if net < 0 else net
    payoff = invoke_payoff(
        "payoff_vertical_credit",
        short_strike=ss,
        long_strike=float(long_c["strike"]) if long_c else ss - 5,
        net_credit=credit,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["bull_put_spread_credit"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_straddle(ctx: BuildContext, *, short: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    call_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    put_c = nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    strike = float(call_c["strike"] if call_c else (put_c["strike"] if put_c else ctx.spot))
    call_c = call_c or contract_at_strike(ctx.contracts, "call", strike)
    put_c = put_c or contract_at_strike(ctx.contracts, "put", strike)
    action = "sell" if short else "buy"
    legs = [lg for lg in [make_option_leg(action, call_c, expiry=ctx.front_expiry), make_option_leg(action, put_c, expiry=ctx.front_expiry)] if lg]
    cm = (legs[0].get("mid") or 0) if legs else 0
    pm = (legs[1].get("mid") or 0) if len(legs) > 1 else 0
    ref = "payoff_short_straddle" if short else "payoff_long_straddle"
    payoff = invoke_payoff(ref, call_premium=cm, put_premium=pm, strike=strike, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_straddle"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_strangle(ctx: BuildContext, *, short: bool = False, guts: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if guts:
        put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.45)
        call_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.45)
    else:
        put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
        call_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
    action = "sell" if short else "buy"
    legs = [lg for lg in [make_option_leg(action, call_c, expiry=ctx.front_expiry), make_option_leg(action, put_c, expiry=ctx.front_expiry)] if lg]
    ps = float((put_c or {}).get("strike") or ctx.spot - 5)
    cs = float((call_c or {}).get("strike") or ctx.spot + 5)
    cm = (legs[0].get("mid") or 0) if legs else 0
    pm = (legs[1].get("mid") or 0) if len(legs) > 1 else 0
    if guts and not short:
        ref = "payoff_long_guts"
        payoff = invoke_payoff(ref, call_premium=cm, put_premium=pm, call_strike=cs, put_strike=ps, contract_multiplier=ctx.contract_multiplier)
    elif short:
        payoff = invoke_payoff("payoff_short_strangle", call_premium=cm, put_premium=pm, call_strike=cs, put_strike=ps, contract_multiplier=ctx.contract_multiplier)
    else:
        payoff = invoke_payoff("payoff_long_strangle", call_premium=cm, put_premium=pm, call_strike=cs, put_strike=ps, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_strangle"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_calendar(ctx: BuildContext, side: Side, *, reverse: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strike = float((ctx.recommended or {}).get("strike") or ctx.spot)
    front_c = contract_at_strike(ctx.contracts, side, strike) or nearest_strike_contract(ctx.contracts, side, strike)
    back_c = contract_at_strike(ctx.back_month_contracts, side, strike)
    if reverse:
        legs = [lg for lg in [make_option_leg("buy", front_c, expiry=ctx.front_expiry), make_option_leg("sell", back_c, expiry=ctx.back_expiry)] if lg]
    else:
        legs = [lg for lg in [make_option_leg("sell", front_c, expiry=ctx.front_expiry), make_option_leg("buy", back_c, expiry=ctx.back_expiry)] if lg]
    legs = [l for l in legs if l.get("symbol")]
    if len(legs) != 2:
        m = _empty_metrics(ctx.contract_multiplier)
        m["legs"] = legs
        m["validation_blocked"] = True
        return legs, m
    net, nt = net_debit_credit(legs)
    fd = dte_from_expiry(ctx.front_expiry) or 30
    bd = dte_from_expiry(ctx.back_expiry) or fd + 30
    payoff = invoke_payoff(
        "payoff_calendar_spread",
        spot=ctx.spot,
        strike=strike,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["calendar_spread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_diagonal(ctx: BuildContext, *, bullish: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    side: Side = "call" if bullish else "put"
    back_pool = ctx.back_month_contracts or ctx.contracts
    long_c = pick_strike(back_pool, side, ctx.spot, 0.55) or nearest_strike_contract(back_pool, side, ctx.spot)
    short_c = None
    if long_c:
        ls = float(long_c["strike"])
        short_c = next_higher_strike(ctx.contracts, side, ls) if bullish else next_lower_strike(ctx.contracts, side, ls)
    legs = [lg for lg in [make_option_leg("buy", long_c, expiry=ctx.back_expiry), make_option_leg("sell", short_c, expiry=ctx.front_expiry)] if lg]
    legs = [l for l in legs if l.get("symbol")]
    if len(legs) != 2:
        m = _empty_metrics(ctx.contract_multiplier)
        m["legs"] = legs
        m["validation_blocked"] = True
        return legs, m
    net, nt = net_debit_credit(legs)
    strike = float(long_c["strike"]) if long_c else ctx.spot
    fd = dte_from_expiry(ctx.front_expiry) or 30
    bd = dte_from_expiry(ctx.back_expiry) or fd + 30
    payoff = invoke_payoff(
        "payoff_calendar_spread",
        spot=ctx.spot,
        strike=strike,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["diagonal_spread_bullish"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_double_calendar(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    call_legs, _ = _build_calendar(ctx, "call")
    put_legs, _ = _build_calendar(ctx, "put")
    legs = call_legs + put_legs
    if len(legs) != 4:
        m = _empty_metrics(ctx.contract_multiplier)
        m["legs"] = legs
        m["validation_blocked"] = True
        return legs, m
    net, nt = net_debit_credit(legs)
    strike = float(ctx.spot)
    fd = dte_from_expiry(ctx.front_expiry) or 30
    bd = dte_from_expiry(ctx.back_expiry) or fd + 30
    payoff = invoke_payoff(
        "payoff_double_calendar",
        spot=ctx.spot,
        strike=strike,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["double_calendar"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_iron_condor(ctx: BuildContext, *, long: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_put = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
    long_put = next_lower_strike(ctx.contracts, "put", float(short_put["strike"])) if short_put else None
    short_call = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
    long_call = next_higher_strike(ctx.contracts, "call", float(short_call["strike"])) if short_call else None
    if long:
        plan = [("buy", long_put), ("sell", short_put), ("buy", long_call), ("sell", short_call)]
    else:
        plan = [("sell", short_put), ("buy", long_put), ("sell", short_call), ("buy", long_call)]
    legs = [lg for action, c in plan if (lg := make_option_leg(action, c, expiry=ctx.front_expiry))]
    legs = normalize_leg_mids([l for l in legs if l.get("symbol")])
    net, nt = net_debit_credit(legs)
    credit = round(-net, 4) if net < 0 else 0.0
    sp = float(short_put["strike"]) if short_put else ctx.spot - 5
    lp = float(long_put["strike"]) if long_put else ctx.spot - 10
    sc = float(short_call["strike"]) if short_call else ctx.spot + 5
    lc = float(long_call["strike"]) if long_call else ctx.spot + 10
    if long:
        payoff = invoke_payoff(
            "payoff_long_iron_condor",
            short_put_strike=sp,
            long_put_strike=lp,
            short_call_strike=sc,
            long_call_strike=lc,
            net_debit=round(net, 4) if net >= 0 else round(abs(net), 4),
            contract_multiplier=ctx.contract_multiplier,
        )
    else:
        payoff = invoke_payoff(
            "payoff_iron_condor",
            short_put_strike=sp,
            long_put_strike=lp,
            short_call_strike=sc,
            long_call_strike=lc,
            net_credit=credit,
            contract_multiplier=ctx.contract_multiplier,
        )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["short_iron_condor"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_butterfly(ctx: BuildContext, side: Side, *, short: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strikes = sorted_strikes(ctx.contracts, side)
    if len(strikes) < 3:
        return [], _empty_metrics(ctx.contract_multiplier)
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - ctx.spot))
    mid_idx = max(0, min(atm_idx, len(strikes) - 2))
    k1, k2, k3 = strikes[mid_idx], strikes[mid_idx + 1], strikes[mid_idx + 2]
    c1 = contract_at_strike(ctx.contracts, side, k1)
    c2 = contract_at_strike(ctx.contracts, side, k2)
    c3 = contract_at_strike(ctx.contracts, side, k3)
    if short:
        legs = [lg for lg in [
            make_option_leg("sell", c1, expiry=ctx.front_expiry),
            make_option_leg("buy", c2, expiry=ctx.front_expiry, quantity=2),
            make_option_leg("sell", c3, expiry=ctx.front_expiry),
        ] if lg]
    else:
        legs = [lg for lg in [
            make_option_leg("buy", c1, expiry=ctx.front_expiry),
            make_option_leg("sell", c2, expiry=ctx.front_expiry, quantity=2),
            make_option_leg("buy", c3, expiry=ctx.front_expiry),
        ] if lg]
    net, nt = net_debit_credit(legs)
    ref = "payoff_short_butterfly" if short else "payoff_butterfly"
    kwargs: dict[str, Any] = dict(
        lower_strike=k1, middle_strike=k2, upper_strike=k3, side=side, contract_multiplier=ctx.contract_multiplier
    )
    if short:
        kwargs["net_credit"] = -net if net < 0 else net
    else:
        kwargs["net_debit"] = net
    payoff = invoke_payoff(ref, **kwargs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_call_butterfly"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_iron_butterfly(ctx: BuildContext, *, long: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    atm = ctx.spot
    sp = nearest_strike_contract(ctx.contracts, "put", atm)
    sc = nearest_strike_contract(ctx.contracts, "call", atm)
    k = float(sp["strike"] if sp else (sc["strike"] if sc else atm))
    sp = sp or contract_at_strike(ctx.contracts, "put", k)
    sc = sc or contract_at_strike(ctx.contracts, "call", k)
    lp = next_lower_strike(ctx.contracts, "put", k)
    lc = next_higher_strike(ctx.contracts, "call", k)
    if long:
        plan = [("buy", sp), ("sell", lp), ("buy", sc), ("sell", lc)]
    else:
        plan = [("sell", sp), ("buy", lp), ("sell", sc), ("buy", lc)]
    legs = [lg for action, c in plan if (lg := make_option_leg(action, c, expiry=ctx.front_expiry))]
    net, nt = net_debit_credit(legs)
    ref = "payoff_long_iron_butterfly" if long else "payoff_iron_butterfly"
    kwargs = dict(
        put_long_strike=float(lp["strike"]) if lp else k - 5,
        put_short_strike=k,
        call_short_strike=k,
        call_long_strike=float(lc["strike"]) if lc else k + 5,
        contract_multiplier=ctx.contract_multiplier,
    )
    if long:
        kwargs["net_debit"] = net
    else:
        kwargs["net_credit"] = -net if net < 0 else net
    payoff = invoke_payoff(ref, **kwargs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["iron_butterfly"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_christmas_tree(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    long_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.55) or nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    if not long_c:
        return [], _empty_metrics(ctx.contract_multiplier)
    ls = float(long_c["strike"])
    s1 = next_higher_strike(ctx.contracts, "call", ls)
    s2 = next_higher_strike(ctx.contracts, "call", float(s1["strike"])) if s1 else None
    legs = [lg for lg in [
        make_option_leg("buy", long_c, expiry=ctx.front_expiry),
        make_option_leg("sell", s1, expiry=ctx.front_expiry),
        make_option_leg("sell", s2, expiry=ctx.front_expiry),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_christmas_tree",
        long_strike=ls,
        short_strike_low=float(s1["strike"]) if s1 else ls + 5,
        short_strike_high=float(s2["strike"]) if s2 else ls + 10,
        net_debit=net,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["christmas_tree_spread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_strip_strap(ctx: BuildContext, *, strip: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    call_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    put_c = nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    strike = float(call_c["strike"] if call_c else ctx.spot)
    if strip:
        legs = [lg for lg in [
            make_option_leg("buy", call_c, expiry=ctx.front_expiry),
            make_option_leg("buy", put_c, expiry=ctx.front_expiry, quantity=2),
        ] if lg]
        cm = mid(call_c) or 0
        pm = mid(put_c) or 0
        payoff = invoke_payoff("payoff_strip", call_premium=cm, put_premium=pm, strike=strike, contract_multiplier=ctx.contract_multiplier)
    else:
        legs = [lg for lg in [
            make_option_leg("buy", call_c, expiry=ctx.front_expiry, quantity=2),
            make_option_leg("buy", put_c, expiry=ctx.front_expiry),
        ] if lg]
        cm = mid(call_c) or 0
        pm = mid(put_c) or 0
        payoff = invoke_payoff("payoff_strap", call_premium=cm, put_premium=pm, strike=strike, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["strip"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_pmcc(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    long_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.70) or nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    short_c = next_higher_strike(ctx.contracts, "call", float(long_c["strike"])) if long_c else None
    legs = [lg for lg in [
        make_option_leg("buy", long_c, expiry=ctx.front_expiry),
        make_option_leg("sell", short_c, expiry=ctx.front_expiry),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_pmcc",
        long_strike=float(long_c["strike"]) if long_c else ctx.spot,
        short_strike=float(short_c["strike"]) if short_c else ctx.spot + 5,
        net_debit=net,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["poor_mans_covered_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_condor(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strikes = sorted_strikes(ctx.contracts, side)
    if len(strikes) < 4:
        return [], _empty_metrics(ctx.contract_multiplier)
    idx = max(0, min(len(strikes) - 4, 1))
    k1, k2, k3, k4 = strikes[idx], strikes[idx + 1], strikes[idx + 2], strikes[idx + 3]
    legs = [lg for lg in [
        make_option_leg("buy", contract_at_strike(ctx.contracts, side, k1), expiry=ctx.front_expiry),
        make_option_leg("sell", contract_at_strike(ctx.contracts, side, k2), expiry=ctx.front_expiry),
        make_option_leg("sell", contract_at_strike(ctx.contracts, side, k3), expiry=ctx.front_expiry),
        make_option_leg("buy", contract_at_strike(ctx.contracts, side, k4), expiry=ctx.front_expiry),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff("payoff_condor_spread", k1=k1, k2=k2, k3=k3, k4=k4, net_debit=net, side=side, contract_multiplier=ctx.contract_multiplier)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["condor_spread_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_ratio(ctx: BuildContext, side: Side, *, long_qty: int = 1, short_qty: int = 2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    long_c = pick_strike(ctx.contracts, side, ctx.spot, 0.55) or nearest_strike_contract(ctx.contracts, side, ctx.spot)
    short_c = next_higher_strike(ctx.contracts, side, float(long_c["strike"])) if long_c and side == "call" else next_lower_strike(ctx.contracts, side, float(long_c["strike"])) if long_c else None
    legs = [lg for lg in [
        make_option_leg("buy", long_c, expiry=ctx.front_expiry, quantity=long_qty),
        make_option_leg("sell", short_c, expiry=ctx.front_expiry, quantity=short_qty),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_multi_leg_scan",
        legs=legs,
        spot=ctx.spot,
        contract_multiplier=ctx.contract_multiplier,
        unlimited_loss=True,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["ratio_spread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_backspread(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_c = pick_strike(ctx.contracts, side, ctx.spot, 0.45) or nearest_strike_contract(ctx.contracts, side, ctx.spot)
    long_c = next_higher_strike(ctx.contracts, side, float(short_c["strike"]), wide=True) if short_c and side == "call" else next_lower_strike(ctx.contracts, side, float(short_c["strike"]), wide=True) if short_c else None
    legs = [lg for lg in [
        make_option_leg("sell", short_c, expiry=ctx.front_expiry),
        make_option_leg("buy", long_c, expiry=ctx.front_expiry, quantity=2),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_backspread",
        short_strike=float(short_c["strike"]) if short_c else ctx.spot,
        long_strike=float(long_c["strike"]) if long_c else ctx.spot + 10,
        net_credit=-net if net < 0 else 0,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["call_backspread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_jade_lizard(ctx: BuildContext, *, reverse: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if reverse:
        sc = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
        sp = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
        lp = next_lower_strike(ctx.contracts, "put", float(sp["strike"])) if sp else None
        legs = [lg for lg in [make_option_leg("sell", sc, expiry=ctx.front_expiry), make_option_leg("sell", sp, expiry=ctx.front_expiry), make_option_leg("buy", lp, expiry=ctx.front_expiry)] if lg]
        net, nt = net_debit_credit(legs)
        payoff = invoke_payoff("payoff_multi_leg_scan", legs=legs, spot=ctx.spot, contract_multiplier=ctx.contract_multiplier, unlimited_loss=True)
    else:
        sp = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
        sc = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
        lc = next_higher_strike(ctx.contracts, "call", float(sc["strike"])) if sc else None
        legs = [lg for lg in [make_option_leg("sell", sp, expiry=ctx.front_expiry), make_option_leg("sell", sc, expiry=ctx.front_expiry), make_option_leg("buy", lc, expiry=ctx.front_expiry)] if lg]
        net, nt = net_debit_credit(legs)
        credit = -net if net < 0 else net
        payoff = invoke_payoff(
            "payoff_jade_lizard",
            short_put_strike=float(sp["strike"]) if sp else ctx.spot - 5,
            short_call_strike=float(sc["strike"]) if sc else ctx.spot + 5,
            long_call_strike=float(lc["strike"]) if lc else ctx.spot + 10,
            net_credit=credit,
            contract_multiplier=ctx.contract_multiplier,
        )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["jade_lizard"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_box_spread(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    k1 = ctx.spot - 5
    k2 = ctx.spot + 5
    strikes = sorted_strikes(ctx.contracts, "call")
    if len(strikes) >= 2:
        k1, k2 = strikes[0], strikes[min(2, len(strikes) - 1)]
    bc = contract_at_strike(ctx.contracts, "call", k1)
    sc = contract_at_strike(ctx.contracts, "call", k2)
    bp = contract_at_strike(ctx.contracts, "put", k2)
    sp = contract_at_strike(ctx.contracts, "put", k1)
    legs = [lg for lg in [
        make_option_leg("buy", bc, expiry=ctx.front_expiry),
        make_option_leg("sell", sc, expiry=ctx.front_expiry),
        make_option_leg("buy", bp, expiry=ctx.front_expiry),
        make_option_leg("sell", sp, expiry=ctx.front_expiry),
    ] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff("payoff_box_spread", lower_strike=k1, upper_strike=k2, net_debit=net, contract_multiplier=ctx.contract_multiplier)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["box_spread"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_reversal(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("sell", ctx.spot, ctx.ticker)
    strike = ctx.spot
    call_c = nearest_strike_contract(ctx.contracts, "call", strike)
    put_c = nearest_strike_contract(ctx.contracts, "put", strike)
    if call_c:
        strike = float(call_c["strike"])
        put_c = put_c or contract_at_strike(ctx.contracts, "put", strike)
    legs = [stock]
    for action, c in [("buy", call_c), ("sell", put_c)]:
        lg = make_option_leg(action, c, expiry=ctx.front_expiry)
        if lg:
            legs.append(lg)
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff("payoff_conversion", strike=strike, net_debit=net, contract_multiplier=ctx.contract_multiplier)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["reversal"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_risk_reversal(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
    call_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
    legs = [lg for lg in [make_option_leg("buy", call_c, expiry=ctx.front_expiry), make_option_leg("sell", put_c, expiry=ctx.front_expiry)] if lg]
    cm = mid(call_c) or 0
    pm = mid(put_c) or 0
    payoff = invoke_payoff(
        "payoff_risk_reversal",
        call_strike=float((call_c or {}).get("strike") or ctx.spot + 5),
        put_strike=float((put_c or {}).get("strike") or ctx.spot - 5),
        call_premium=cm,
        put_premium=pm,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["risk_reversal"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_dispersion(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    long_c = contract_at_strike(ctx.contracts, "call", float(short_c["strike"])) if short_c else None
    legs = [lg for lg in [make_option_leg("sell", short_c, expiry=ctx.front_expiry), make_option_leg("buy", long_c, expiry=ctx.front_expiry)] if lg]
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff("payoff_dispersion", net_debit=abs(net), contract_multiplier=ctx.contract_multiplier)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["dispersion_trade"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_covered_put(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("sell", ctx.spot, ctx.ticker)
    put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.30) or nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    put_leg = make_option_leg("sell", put_c, expiry=ctx.front_expiry)
    legs = [stock] + ([put_leg] if put_leg else [])
    prem = mid(put_c) or 0
    payoff = invoke_payoff(
        "payoff_covered_put",
        stock_short_price=ctx.spot,
        put_strike=float((put_c or {}).get("strike") or ctx.spot - 5),
        put_premium=prem,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["covered_put"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_stock_long_put(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.25)
    put_leg = make_option_leg("buy", put_c, expiry=ctx.front_expiry)
    legs = [stock] + ([put_leg] if put_leg else [])
    pp = mid(put_c) or 0
    payoff = invoke_payoff(
        "payoff_protective_put",
        stock_cost=ctx.spot,
        put_strike=float((put_c or {}).get("strike") or ctx.spot - 5),
        put_premium=pp,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["stock_long_put"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_conversion(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    strike = ctx.spot
    call_c = nearest_strike_contract(ctx.contracts, "call", strike)
    put_c = nearest_strike_contract(ctx.contracts, "put", strike)
    if call_c:
        strike = float(call_c["strike"])
        put_c = put_c or contract_at_strike(ctx.contracts, "put", strike)
    legs = [stock]
    for action, c in [("sell", call_c), ("buy", put_c)]:
        lg = make_option_leg(action, c, expiry=ctx.front_expiry)
        if lg:
            legs.append(lg)
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff("payoff_conversion", strike=strike, net_debit=net, contract_multiplier=ctx.contract_multiplier)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["conversion"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_leveraged_covered_call(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    call_c = resolve_contract_from_recommended(ctx.contracts, ctx.recommended, "call", ctx.spot, delta_target=0.55)
    call_leg = make_option_leg("buy", call_c, expiry=ctx.front_expiry)
    legs = [stock] + ([call_leg] if call_leg else [])
    prem = (call_leg or {}).get("mid") or 0
    payoff = invoke_payoff(
        "payoff_leveraged_covered_call",
        stock_cost=ctx.spot,
        call_premium=prem,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["leveraged_covered_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_covered_call(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    call_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.30) or nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    call_leg = make_option_leg("sell", call_c, expiry=ctx.front_expiry)
    legs = [stock] + ([call_leg] if call_leg else [])
    prem = (call_leg or {}).get("mid") or 0
    payoff = invoke_payoff(
        "payoff_covered_call",
        stock_cost=ctx.spot,
        call_strike=float((call_c or {}).get("strike") or ctx.spot + 5),
        call_premium=prem,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["covered_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_collar(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    put_c = pick_strike(ctx.contracts, "put", ctx.spot, 0.25)
    call_c = pick_strike(ctx.contracts, "call", ctx.spot, 0.25)
    legs = [stock]
    for action, c in [("buy", put_c), ("sell", call_c)]:
        lg = make_option_leg(action, c, expiry=ctx.front_expiry)
        if lg:
            legs.append(lg)
    pp = mid(put_c) or 0
    cp = mid(call_c) or 0
    payoff = invoke_payoff(
        "payoff_collar",
        stock_cost=ctx.spot,
        put_strike=float((put_c or {}).get("strike") or ctx.spot - 5),
        call_strike=float((call_c or {}).get("strike") or ctx.spot + 5),
        put_premium=pp,
        call_premium=cp,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["collar"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_synthetic(ctx: BuildContext, *, long: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    call_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    put_c = nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    strike = float(call_c["strike"] if call_c else (put_c["strike"] if put_c else ctx.spot))
    if long:
        legs = [lg for lg in [make_option_leg("buy", call_c, expiry=ctx.front_expiry), make_option_leg("sell", put_c, expiry=ctx.front_expiry)] if lg]
        cm = mid(call_c) or 0
        pm = mid(put_c) or 0
        payoff = invoke_payoff("payoff_synthetic_long", call_strike=strike, call_premium=cm, put_premium=pm, contract_multiplier=ctx.contract_multiplier)
    else:
        legs = [lg for lg in [make_option_leg("sell", call_c, expiry=ctx.front_expiry), make_option_leg("buy", put_c, expiry=ctx.front_expiry)] if lg]
        cm = mid(call_c) or 0
        pm = mid(put_c) or 0
        payoff = invoke_payoff("payoff_synthetic_short", call_strike=strike, call_premium=cm, put_premium=pm, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    sid = "synthetic_long_stock" if long else "synthetic_short_stock"
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY[sid]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_apex(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    front_call = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
    front_put = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
    back_call = contract_at_strike(ctx.back_month_contracts, "call", float(front_call["strike"])) if front_call else None
    back_put = contract_at_strike(ctx.back_month_contracts, "put", float(front_put["strike"])) if front_put else None
    plan = [
        ("buy", back_call, ctx.back_expiry),
        ("buy", back_put, ctx.back_expiry),
        ("sell", front_call, ctx.front_expiry),
        ("sell", front_put, ctx.front_expiry),
    ]
    legs = [lg for action, c, exp in plan if (lg := make_option_leg(action, c, expiry=exp))]
    legs = [l for l in legs if l.get("symbol")]
    if len(legs) != 4:
        m = _empty_metrics(ctx.contract_multiplier)
        m["legs"] = legs
        m["validation_blocked"] = True
        return legs, m
    net, nt = net_debit_credit(legs)
    cs = float(front_call["strike"]) if front_call else ctx.spot
    ps = float(front_put["strike"]) if front_put else ctx.spot
    fd = dte_from_expiry(ctx.front_expiry) or 7
    bd = dte_from_expiry(ctx.back_expiry) or fd + 14
    payoff = invoke_payoff(
        "payoff_apex_strategy",
        spot=ctx.spot,
        call_strike=cs,
        put_strike=ps,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = STRATEGY_REGISTRY["apex_strategy"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


# strategy_id → builder
BUILDERS: dict[str, Any] = {
    "long_call": lambda c: _build_single_long(c, "call"),
    "long_put": lambda c: _build_single_long(c, "put"),
    "naked_call": lambda c: _build_single_short(c, "call"),
    "naked_put": lambda c: _build_single_short(c, "put"),
    "apex_benchmark_greeks_strategy": lambda c: _build_single_long(c, "call"),
    "long_call_leaps": lambda c: _build_single_long(c, "call"),
    "long_put_leaps": lambda c: _build_single_long(c, "put"),
    "deep_itm_call": lambda c: _build_single_long(c, "call"),
    "deep_itm_put": lambda c: _build_single_long(c, "put"),
    "atm_call": lambda c: _build_single_long(c, "call"),
    "vix_call_hedge": lambda c: _build_single_long(c, "call"),
    "wheel_strategy": lambda c: _build_single_short(c, "put"),
    "bull_call_spread": lambda c: _build_vertical_debit(c, "call"),
    "bear_put_spread": lambda c: _build_vertical_debit(c, "put"),
    "call_debit_spread": lambda c: _build_vertical_debit(c, "call"),
    "put_debit_spread": lambda c: _build_vertical_debit(c, "put"),
    "wide_bull_call_spread": lambda c: _build_vertical_debit(c, "call", wide=True),
    "wide_bear_put_spread": lambda c: _build_vertical_debit(c, "put", wide=True),
    "vega_neutral_spread": lambda c: _build_vertical_debit(c, "call"),
    "bull_put_spread_credit": lambda c: _build_vertical_credit(c, "put"),
    "bear_call_spread_credit": lambda c: _build_vertical_credit(c, "call"),
    "call_credit_spread": lambda c: _build_vertical_credit(c, "call"),
    "put_credit_spread": lambda c: _build_vertical_credit(c, "put"),
    "long_straddle": lambda c: _build_straddle(c),
    "long_straddle_leaps": lambda c: _build_straddle(c),
    "earnings_straddle": lambda c: _build_straddle(c),
    "long_straddle_pre_earnings": lambda c: _build_straddle(c),
    "gamma_scalping": lambda c: _build_straddle(c),
    "synthetic_straddle": lambda c: _build_straddle(c),
    "short_straddle": lambda c: _build_straddle(c, short=True),
    "long_strangle": lambda c: _build_strangle(c),
    "short_strangle": lambda c: _build_strangle(c, short=True),
    "long_guts": lambda c: _build_strangle(c, guts=True),
    "short_guts": lambda c: _build_strangle(c, short=True, guts=True),
    "strip": lambda c: _build_strip_strap(c, strip=True),
    "strap": lambda c: _build_strip_strap(c, strip=False),
    "calendar_spread": lambda c: _build_calendar(c, "call"),
    "calendar_put_spread": lambda c: _build_calendar(c, "put"),
    "calendar_call_spread": lambda c: _build_calendar(c, "call"),
    "reverse_calendar": lambda c: _build_calendar(c, "call", reverse=True),
    "double_calendar": _build_double_calendar,
    "calendar_straddle": _build_double_calendar,
    "diagonal_spread_bullish": lambda c: _build_diagonal(c, bullish=True),
    "diagonal_spread_bearish": lambda c: _build_diagonal(c, bullish=False),
    "diagonal_call_spread": lambda c: _build_diagonal(c, bullish=True),
    "double_diagonal": _build_double_calendar,
    "short_iron_condor": lambda c: _build_iron_condor(c),
    "iv_crush_short_iron_condor": lambda c: _build_iron_condor(c),
    "theta_harvest_iron_condor": lambda c: _build_iron_condor(c),
    "iron_condor_monthly": lambda c: _build_iron_condor(c),
    "iron_condor_wide": lambda c: _build_iron_condor(c),
    "long_iron_condor": lambda c: _build_iron_condor(c, long=True),
    "reverse_iron_condor": lambda c: _build_iron_condor(c, long=True),
    "long_call_butterfly": lambda c: _build_butterfly(c, "call"),
    "long_put_butterfly": lambda c: _build_butterfly(c, "put"),
    "short_call_butterfly": lambda c: _build_butterfly(c, "call", short=True),
    "short_put_butterfly": lambda c: _build_butterfly(c, "put", short=True),
    "iron_butterfly": lambda c: _build_iron_butterfly(c),
    "long_iron_butterfly": lambda c: _build_iron_butterfly(c, long=True),
    "short_iron_butterfly_variant": lambda c: _build_iron_butterfly(c),
    "broken_wing_butterfly": lambda c: _build_butterfly(c, "call"),
    "skip_strike_butterfly": lambda c: _build_butterfly(c, "call"),
    "condor_spread_call": lambda c: _build_condor(c, "call"),
    "condor_spread_put": lambda c: _build_condor(c, "put"),
    "ratio_spread": lambda c: _build_ratio(c, "call"),
    "call_ratio_spread": lambda c: _build_ratio(c, "call"),
    "put_ratio_spread": lambda c: _build_ratio(c, "put"),
    "one_by_two_ratio_spread": lambda c: _build_ratio(c, "call", long_qty=1, short_qty=2),
    "two_by_one_ratio_spread": lambda c: _build_ratio(c, "call", long_qty=2, short_qty=1),
    "back_ratio_spread": lambda c: _build_backspread(c, "call"),
    "call_backspread": lambda c: _build_backspread(c, "call"),
    "put_backspread": lambda c: _build_backspread(c, "put"),
    "jade_lizard": lambda c: _build_jade_lizard(c),
    "reverse_jade_lizard": lambda c: _build_jade_lizard(c, reverse=True),
    "covered_call": _build_covered_call,
    "stock_short_call": _build_covered_call,
    "poor_mans_covered_call": _build_pmcc,
    "covered_put": lambda c: _build_covered_put(c),
    "married_put": lambda c: _build_single_long(c, "put", delta_target=0.30),
    "leveraged_covered_call": _build_leveraged_covered_call,
    "stock_long_put": _build_stock_long_put,
    "protective_collar": _build_collar,
    "collar": _build_collar,
    "synthetic_long_stock": lambda c: _build_synthetic(c, long=True),
    "synthetic_short_stock": lambda c: _build_synthetic(c, long=False),
    "synthetic_call": lambda c: _build_synthetic(c, long=True),
    "synthetic_put": lambda c: _build_synthetic(c, long=False),
    "long_combo": lambda c: _build_synthetic(c, long=True),
    "short_combo": lambda c: _build_synthetic(c, long=False),
    "conversion": _build_conversion,
    "reversal": _build_reversal,
    "box_spread": _build_box_spread,
    "risk_reversal": _build_risk_reversal,
    "volatility_skew_trade": _build_risk_reversal,
    "dispersion_trade": _build_dispersion,
    "apex_strategy": _build_apex,
    "jelly_roll": _build_double_calendar,
    "christmas_tree_spread": _build_christmas_tree,
}


def build_registry_metrics(
    strategy_id: str,
    *,
    spot: float,
    contracts: list[dict[str, Any]],
    back_month_contracts: list[dict[str, Any]] | None = None,
    front_expiry: str | None = None,
    back_expiry: str | None = None,
    iv: float | None = None,
    ticker: str = "",
    contract_multiplier: int = 100,
    recommended: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    spec = STRATEGY_REGISTRY.get(strategy_id)
    if not spec or spec.leg_count == 0:
        return None
    if not contracts or spot is None:
        return _empty_metrics(contract_multiplier)

    ctx = BuildContext(
        strategy_id=strategy_id,
        spot=float(spot),
        contracts=contracts,
        back_month_contracts=back_month_contracts or [],
        front_expiry=front_expiry,
        back_expiry=back_expiry,
        iv=iv if iv and iv > 0 else 0.25,
        ticker=ticker or "SYM",
        contract_multiplier=contract_multiplier,
        recommended=recommended,
    )

    builder = BUILDERS.get(strategy_id)
    if not builder:
        return None

    _, metrics = builder(ctx)
    return metrics


def from_display_name(
    strategy_name: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    from app.strategies.registry import resolve_strategy_id

    sid = resolve_strategy_id(strategy_name)
    if not sid:
        return None
    return build_registry_metrics(sid, **kwargs)
