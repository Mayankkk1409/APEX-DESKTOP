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
from app.strategies.structure_math import (
    NO_CLOSED_FORM_PAYOFF_REFS,
    REMAINING_LONG_LEG_NOTE,
    documented_metric_overrides,
    quote_documented_structure,
)

Side = Literal["call", "put"]

# A LEAPS contract is more than one year from today.
LEAPS_MIN_DTE = 365
# Deep in the money means at least this far through the spot.
DEEP_ITM_FRACTION = 0.10


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
    shares_held: int = 0
    shares_encumbered: int = 0
    shares_short: int = 0
    share_avg_cost: float | None = None
    stock_ask: float | None = None
    component_contracts: list[dict[str, Any]] | None = None
    component_ticker: str | None = None
    hv: float | None = None


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
    loss = metrics.get("max_loss")
    if isinstance(loss, (int, float)) and not isinstance(loss, bool):
        metrics["max_loss"] = round(abs(float(loss)), 2)
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
    quoted = quote_documented_structure(spec, legs, contract_multiplier=mult)
    if quoted is not None:
        metrics.update(documented_metric_overrides(quoted))
    # Undefined-risk structures do not get a scanned stand-in for the unbounded side.
    if spec.risk_type == "undefined":
        # A builder can mark the loss side finite when the legs are net long.
        if payoff.get("max_loss_unlimited_allowed") is False:
            metrics["max_loss"] = None
            metrics["max_loss_unlimited_allowed"] = False
        elif spec.max_loss_type == "unlimited" or spec.max_loss_type == "variable":
            metrics["max_loss"] = None
            metrics["max_loss_unlimited_allowed"] = True
        elif spec.payoff_function_ref not in {"payoff_vertical_debit", "payoff_vertical_credit", "payoff_iron_condor", "payoff_long_iron_condor"}:
            metrics["max_loss"] = None
            metrics["max_loss_unlimited_allowed"] = True
        if spec.max_profit_type == "unlimited" or payoff.get("max_profit_unlimited_allowed") is True:
            metrics["max_profit"] = None
            metrics["max_profit_unlimited_allowed"] = True
    if spec.payoff_function_ref in NO_CLOSED_FORM_PAYOFF_REFS and quoted is None:
        # Drop a scanned or simplified max profit. Keep Unlimited when that side
        # really has no cap. Do not publish a negative scan as max loss.
        unlimited_profit = spec.max_profit_type == "unlimited" or payoff.get("max_profit_unlimited_allowed") is True
        metrics["max_profit"] = None
        metrics["max_profit_unlimited_allowed"] = unlimited_profit
        metrics["payoff_depends_on_remaining_leg"] = True
        metrics["max_profit_closed_form"] = False
        prior = str(metrics.get("notes") or payoff.get("payoff_notes") or "").strip()
        if REMAINING_LONG_LEG_NOTE not in prior:
            metrics["notes"] = f"{prior} {REMAINING_LONG_LEG_NOTE}".strip()
    return metrics


def _blocked(ctx: BuildContext, reason: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metrics = _empty_metrics(ctx.contract_multiplier)
    metrics["validation_blocked"] = True
    metrics["validation_error"] = reason
    metrics["notes"] = reason
    metrics["max_profit"] = None
    metrics["max_loss"] = None
    metrics["max_profit_unlimited_allowed"] = False
    metrics["max_loss_unlimited_allowed"] = False
    return [], metrics


def _without_closed_form(metrics: dict[str, Any]) -> dict[str, Any]:
    """Drop a scanned dollar max profit or loss. Unlimited is a flag, not a number."""
    metrics["max_profit"] = None
    metrics["max_loss"] = None
    metrics["breakevens"] = []
    metrics["max_profit_unlimited_allowed"] = False
    metrics["max_loss_unlimited_allowed"] = False
    metrics["payoff_depends_on_remaining_leg"] = True
    metrics["max_profit_closed_form"] = False
    return metrics


def _expiry_pools(ctx: BuildContext) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for contract in list(ctx.contracts) + list(ctx.back_month_contracts):
        exp = contract.get("expiry")
        if exp:
            grouped.setdefault(str(exp), []).append(contract)
    if ctx.back_expiry:
        missing = [c for c in ctx.back_month_contracts if not c.get("expiry")]
        if missing:
            grouped.setdefault(str(ctx.back_expiry), []).extend(missing)
    if ctx.front_expiry:
        missing = [c for c in ctx.contracts if not c.get("expiry")]
        if missing:
            grouped.setdefault(str(ctx.front_expiry), []).extend(missing)
    return list(grouped.items())


def _leaps_pool(ctx: BuildContext) -> tuple[str, list[dict[str, Any]]] | None:
    best: tuple[int, str, list[dict[str, Any]]] | None = None
    for expiry, rows in _expiry_pools(ctx):
        dte = dte_from_expiry(expiry)
        if dte is None or dte <= LEAPS_MIN_DTE:
            continue
        if best is None or dte < best[0]:
            best = (dte, expiry, rows)
    if best is None:
        return None
    return best[1], best[2]


def _deep_itm_contract(contracts: list[dict[str, Any]], side: Side, spot: float) -> dict[str, Any] | None:
    """Nearest strike that is at least 10% in the money. At-the-money is not eligible."""
    if side == "call":
        ceiling = spot * (1.0 - DEEP_ITM_FRACTION)
        pool = [c for c in contracts if c.get("side") == "call" and c.get("strike") is not None and float(c["strike"]) <= ceiling + 1e-6]
        if not pool:
            return None
        return max(pool, key=lambda c: float(c["strike"]))
    floor = spot * (1.0 + DEEP_ITM_FRACTION)
    pool = [c for c in contracts if c.get("side") == "put" and c.get("strike") is not None and float(c["strike"]) >= floor - 1e-6]
    if not pool:
        return None
    return min(pool, key=lambda c: float(c["strike"]))


def _otm_contract(contracts: list[dict[str, Any]], side: Side, spot: float) -> dict[str, Any] | None:
    if side == "call":
        pool = [c for c in contracts if c.get("side") == "call" and c.get("strike") is not None and float(c["strike"]) > spot]
        if not pool:
            return None
        return min(pool, key=lambda c: float(c["strike"]))
    pool = [c for c in contracts if c.get("side") == "put" and c.get("strike") is not None and float(c["strike"]) < spot]
    if not pool:
        return None
    return max(pool, key=lambda c: float(c["strike"]))


def _contract_vega(contract: dict[str, Any], *, spot: float, expiry: str | None, iv_fallback: float) -> float | None:
    raw = contract.get("vega")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) > 0:
        return float(raw)
    strike = contract.get("strike")
    if strike is None:
        return None
    exp = str(contract.get("expiry") or expiry or "")
    dte = dte_from_expiry(exp)
    iv = contract.get("iv") if isinstance(contract.get("iv"), (int, float)) else iv_fallback
    if dte is None or dte <= 0 or not isinstance(iv, (int, float)) or float(iv) <= 0:
        return None
    from app.analysis.black_scholes import greeks

    side = contract.get("side") if contract.get("side") in {"call", "put"} else "call"
    model = greeks(spot=spot, strike=float(strike), years=dte / 365.0, vol=float(iv), side=side)
    if model is None or model.vega <= 0:
        return None
    return float(model.vega)


def _vega_quantities(front_vega: float, back_vega: float) -> tuple[int, int] | None:
    """Small long/short counts whose vegas cancel. None when no ratio is close."""
    if front_vega <= 0 or back_vega <= 0:
        return None
    best: tuple[float, int, int, int] | None = None
    for back_qty in range(1, 9):
        for front_qty in range(1, 9):
            long_vega = front_qty * front_vega
            short_vega = back_qty * back_vega
            scale = max(long_vega, short_vega)
            rel = abs(long_vega - short_vega) / scale
            score = (rel, front_qty + back_qty, front_qty, back_qty)
            if best is None or score < best:
                best = score
    if best is None or best[0] > 0.08:
        return None
    return best[2], best[3]


def _build_single_long(ctx: BuildContext, side: Side, *, delta_target: float = 0.55) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    c = resolve_contract_from_recommended(ctx.contracts, ctx.recommended, side, ctx.spot, delta_target=delta_target)
    leg = make_option_leg("buy", c, expiry=ctx.front_expiry)
    if leg and c:
        _copy_greeks(leg, c)
    legs = [leg] if leg else []
    prem = (leg or {}).get("mid") or 0
    strike = float((leg or {}).get("strike") or ctx.spot)
    payoff = invoke_payoff("payoff_long_option", premium=prem, strike=strike, side=side, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    return legs, _finalize(get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_call"], legs, payoff, net, nt, ctx.contract_multiplier)


def _build_benchmark(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rule 1: one long call when the tape is bullish, one long put when it is bearish."""
    hinted = str((ctx.recommended or {}).get("benchmark_side") or (ctx.recommended or {}).get("side") or "call")
    side: Side = "put" if hinted == "put" else "call"
    return _build_single_long(ctx, side, delta_target=0.55)


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
        # Guts use in-the-money wings: call strike below spot, put strike above spot.
        call_c = next_lower_strike(ctx.contracts, "call", ctx.spot) or pick_strike(ctx.contracts, "call", ctx.spot, 0.70)
        put_c = next_higher_strike(ctx.contracts, "put", ctx.spot) or pick_strike(ctx.contracts, "put", ctx.spot, 0.70)
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
        long_front=reverse,
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
    long_iv = long_c.get("iv") if long_c else None
    payoff = invoke_payoff(
        "payoff_calendar_spread",
        spot=ctx.spot,
        strike=strike,
        short_strike=float(short_c["strike"]) if short_c and short_c.get("strike") is not None else strike,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=float(long_iv) if isinstance(long_iv, (int, float)) else ctx.iv,
        back_iv=float(long_iv) if isinstance(long_iv, (int, float)) else ctx.iv,
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


def _build_double_diagonal(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Long back-month call and put, short nearer OTM call and put at different strikes."""
    call_legs, _ = _build_diagonal(ctx, bullish=True)
    put_legs, _ = _build_diagonal(ctx, bullish=False)
    legs = call_legs + put_legs
    if len(legs) != 4:
        metrics = _empty_metrics(ctx.contract_multiplier)
        metrics["legs"] = legs
        metrics["validation_blocked"] = True
        return legs, metrics
    net, nt = net_debit_credit(legs)
    fd = dte_from_expiry(ctx.front_expiry) or 30
    bd = dte_from_expiry(ctx.back_expiry) or fd + 30
    payoff = invoke_payoff(
        "payoff_double_calendar",
        spot=ctx.spot,
        strike=float(ctx.spot),
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["double_diagonal"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_jelly_roll(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Long synthetic in the back month, short synthetic in the front month, one strike."""
    anchor = float((ctx.recommended or {}).get("strike") or ctx.spot)
    front_call = contract_at_strike(ctx.contracts, "call", anchor) or nearest_strike_contract(ctx.contracts, "call", anchor)
    if not front_call:
        return [], _empty_metrics(ctx.contract_multiplier)
    strike = float(front_call["strike"])
    front_put = contract_at_strike(ctx.contracts, "put", strike) or nearest_strike_contract(ctx.contracts, "put", strike)
    back_call = contract_at_strike(ctx.back_month_contracts, "call", strike)
    back_put = contract_at_strike(ctx.back_month_contracts, "put", strike)
    legs = [
        lg
        for lg in (
            make_option_leg("buy", back_call, expiry=ctx.back_expiry),
            make_option_leg("sell", front_call, expiry=ctx.front_expiry),
            make_option_leg("sell", back_put, expiry=ctx.back_expiry),
            make_option_leg("buy", front_put, expiry=ctx.front_expiry),
        )
        if lg and lg.get("symbol")
    ]
    if len(legs) != 4:
        metrics = _empty_metrics(ctx.contract_multiplier)
        metrics["legs"] = legs
        metrics["validation_blocked"] = True
        return legs, metrics
    net, nt = net_debit_credit(legs)
    fd = dte_from_expiry(ctx.front_expiry) or 30
    bd = dte_from_expiry(ctx.back_expiry) or fd + 30
    payoff = invoke_payoff(
        "payoff_jelly_roll",
        spot=ctx.spot,
        strike=strike,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["jelly_roll"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_iron_condor(ctx: BuildContext, *, long: bool = False, wide: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_put = pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
    long_put = next_lower_strike(ctx.contracts, "put", float(short_put["strike"]), wide=wide) if short_put else None
    short_call = pick_strike(ctx.contracts, "call", ctx.spot, 0.20)
    long_call = next_higher_strike(ctx.contracts, "call", float(short_call["strike"]), wide=wide) if short_call else None
    if long:
        # Debit / reverse condor: buy the body, sell the wings.
        plan = [("buy", short_put), ("sell", long_put), ("buy", short_call), ("sell", long_call)]
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
        # Parameter names are the bought and sold strikes, not the short-condor nicknames.
        payoff = invoke_payoff(
            "payoff_long_iron_condor",
            short_put_strike=lp,
            long_put_strike=sp,
            short_call_strike=lc,
            long_call_strike=sc,
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


def _build_butterfly(ctx: BuildContext, side: Side, *, short: bool = False, broken: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strikes = sorted_strikes(ctx.contracts, side)
    if len(strikes) < 3:
        return [], _empty_metrics(ctx.contract_multiplier)
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - ctx.spot))
    mid_idx = max(0, min(atm_idx, len(strikes) - 2))
    upper_step = 3 if broken and mid_idx + 3 < len(strikes) else 2
    k1, k2, k3 = strikes[mid_idx], strikes[mid_idx + 1], strikes[mid_idx + upper_step]
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
    """Long far-dated ITM call, short nearer OTM call. A same-expiry vertical is not this structure."""
    if not ctx.back_month_contracts or not ctx.back_expiry or ctx.back_expiry == ctx.front_expiry:
        return _blocked(
            ctx,
            "Poor man's covered call is a diagonal: long far-dated in-the-money call and short nearer out-of-the-money call. This chain has no later expiration.",
        )
    long_c = _deep_itm_contract(ctx.back_month_contracts, "call", ctx.spot)
    short_c = _otm_contract(ctx.contracts, "call", ctx.spot)
    if long_c is None or short_c is None or float(short_c["strike"]) <= float(long_c["strike"]):
        return _blocked(
            ctx,
            "Poor man's covered call needs a far-dated call at least 10% in the money and a nearer out-of-the-money call. This chain does not have both.",
        )
    long_leg = make_option_leg("buy", long_c, expiry=ctx.back_expiry)
    short_leg = make_option_leg("sell", short_c, expiry=ctx.front_expiry)
    legs = [lg for lg in [long_leg, short_leg] if lg]
    if len(legs) != 2 or legs[0].get("expiry") == legs[1].get("expiry"):
        return _blocked(
            ctx,
            "Poor man's covered call is a diagonal across two expirations. Both calls resolved to the same expiration, so the vertical was not built.",
        )
    net, nt = net_debit_credit(legs)
    payoff = invoke_payoff(
        "payoff_pmcc",
        long_strike=float(long_c["strike"]),
        short_strike=float(short_c["strike"]),
        net_debit=net,
        contract_multiplier=ctx.contract_multiplier,
    )
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["poor_mans_covered_call"]
    _, metrics = legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)
    # The diagonal has no single-expiry max profit. Keep the debit as cash at risk.
    metrics["max_profit"] = None
    metrics["max_profit_unlimited_allowed"] = False
    metrics["breakevens"] = []
    metrics["payoff_depends_on_remaining_leg"] = True
    metrics["max_profit_closed_form"] = False
    return legs, metrics


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
    net_long = long_qty > short_qty
    payoff = invoke_payoff(
        "payoff_multi_leg_scan",
        legs=legs,
        spot=ctx.spot,
        contract_multiplier=ctx.contract_multiplier,
        unlimited_loss=not net_long,
        unlimited_profit=net_long,
    )
    if net_long:
        # Long the extra wing: profit is unlimited, loss is not.
        payoff["max_loss"] = None
        payoff["max_loss_unlimited_allowed"] = False
        payoff["max_profit_unlimited_allowed"] = True
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
    if ctx.strategy_id == "volatility_skew_trade":
        # Sheet: buy the OTM put, sell the OTM call. Upside loss is the naked call.
        legs = [lg for lg in [make_option_leg("buy", put_c, expiry=ctx.front_expiry), make_option_leg("sell", call_c, expiry=ctx.front_expiry)] if lg]
        pm = mid(put_c) or 0
        cm = mid(call_c) or 0
        put_strike = float((put_c or {}).get("strike") or ctx.spot - 5)
        call_strike = float((call_c or {}).get("strike") or ctx.spot + 5)
        payoff = {
            "max_profit": round((put_strike - pm + cm) * ctx.contract_multiplier, 2),
            "max_loss": None,
            "breakevens": [round(put_strike - pm + cm, 2), round(call_strike + cm - pm, 2)],
            "max_profit_iv_assumption_dependent": False,
            "max_profit_unlimited_allowed": False,
            "max_loss_unlimited_allowed": True,
            "payoff_notes": "Buy the OTM put and sell the OTM call. Profit is capped at a stock price of zero. Upside loss is unlimited.",
        }
        net, nt = net_debit_credit(legs)
        spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["volatility_skew_trade"]
        return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)
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
    """Index versus a component. One underlying is not a dispersion trade."""
    component = ctx.component_contracts or []
    other = (ctx.component_ticker or "").strip()
    if not component or not other or other.upper() == ctx.ticker.upper():
        return _blocked(
            ctx,
            "A dispersion trade needs an index and a component. This scan has one underlying, so no legs are built.",
        )
    short_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    if short_c is None:
        return _blocked(ctx, "A dispersion trade needs an at-the-money call on the index. This chain has no call.")
    shared_expiry = str(short_c.get("expiry") or ctx.front_expiry or "")
    long_pool = [c for c in component if not shared_expiry or str(c.get("expiry") or shared_expiry) == shared_expiry]
    component_strikes = sorted_strikes(long_pool or component, "call")
    component_spot = component_strikes[len(component_strikes) // 2] if component_strikes else ctx.spot
    long_c = nearest_strike_contract(long_pool or component, "call", component_spot)
    if long_c is None:
        return _blocked(ctx, "A dispersion trade needs an at-the-money call on the second underlying. That chain has no call.")
    if str(long_c.get("symbol") or "") and str(long_c.get("symbol")) == str(short_c.get("symbol") or ""):
        return _blocked(ctx, "A dispersion trade needs two underlyings. Both calls resolved to the same contract.")
    short_leg = make_option_leg("sell", short_c, expiry=shared_expiry or ctx.front_expiry)
    long_expiry = str(long_c.get("expiry") or shared_expiry or ctx.front_expiry)
    long_leg = make_option_leg("buy", long_c, expiry=long_expiry)
    if short_leg:
        short_leg["underlying"] = ctx.ticker
    if long_leg:
        long_leg["underlying"] = other
    legs = [lg for lg in [short_leg, long_leg] if lg]
    if len(legs) != 2:
        return _blocked(ctx, "A dispersion trade needs a short index call and a long component call. One of those quotes is missing.")
    net, nt = net_debit_credit(legs)
    payoff = {
        "max_profit": None,
        "max_loss": None,
        "breakevens": [],
        "max_profit_unlimited_allowed": False,
        "max_loss_unlimited_allowed": False,
        "payoff_notes": "Dispersion payoff depends on correlation between the two underlyings. No closed-form max profit is shown.",
    }
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["dispersion_trade"]
    _, metrics = legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)
    return legs, _without_closed_form(metrics)


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


def _call_put_at_one_strike(
    contracts: list[dict[str, Any]],
    spot: float,
    *,
    expiry: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Call and put that share one strike. A synthetic is not a split-strike combo."""
    pool = contracts
    if expiry:
        dated = [c for c in contracts if str(c.get("expiry") or "") == str(expiry)]
        if dated:
            pool = dated
    calls: dict[float, dict[str, Any]] = {}
    puts: dict[float, dict[str, Any]] = {}
    for contract in pool:
        raw = contract.get("strike")
        side = contract.get("side")
        if raw is None or side not in {"call", "put"}:
            continue
        bucket = calls if side == "call" else puts
        bucket.setdefault(round(float(raw), 4), contract)
    shared = set(calls) & set(puts)
    if not shared:
        return None, None
    strike = min(shared, key=lambda key: (abs(key - spot), key))
    return calls[strike], puts[strike]


def _build_synthetic(ctx: BuildContext, *, long: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Long stock: buy the call, sell the put. Short stock: sell the call, buy the put. Same strike and expiry."""
    call_c, put_c = _call_put_at_one_strike(ctx.contracts, ctx.spot, expiry=ctx.front_expiry)
    if not call_c or not put_c:
        return _blocked(
            ctx,
            "A synthetic stock position is a call and a put at the same strike and expiry. This chain has no shared strike.",
        )
    strike = float(call_c["strike"])
    if long:
        plan = [("buy", call_c), ("sell", put_c)]
        payoff_ref = "payoff_synthetic_long"
    else:
        plan = [("sell", call_c), ("buy", put_c)]
        payoff_ref = "payoff_synthetic_short"
    legs = [lg for action, contract in plan if (lg := make_option_leg(action, contract, expiry=ctx.front_expiry))]
    same_strike = len({round(float(lg["strike"]), 4) for lg in legs}) == 1
    same_expiry = len({str(lg.get("expiry")) for lg in legs}) == 1
    if len(legs) != 2 or not same_strike or not same_expiry:
        return _blocked(
            ctx,
            "A synthetic stock position is a call and a put at the same strike and expiry. The chain quotes do not line up.",
        )
    payoff = invoke_payoff(
        payoff_ref,
        call_strike=strike,
        call_premium=mid(call_c) or 0,
        put_premium=mid(put_c) or 0,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    sid = "synthetic_long_stock" if long else "synthetic_short_stock"
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY[sid]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _copy_greeks(leg: dict[str, Any], contract: dict[str, Any]) -> None:
    for key in ("delta", "gamma", "theta", "vega"):
        raw = contract.get(key)
        if raw is None:
            continue
        try:
            leg[key] = float(raw)
        except (TypeError, ValueError):
            continue


def _combined_greeks(legs: list[dict[str, Any]]) -> dict[str, float | None]:
    combined: dict[str, float | None] = {}
    for key in ("delta", "gamma", "theta", "vega"):
        total = 0.0
        seen = False
        for leg in legs:
            raw = leg.get(key)
            if raw is None:
                continue
            seen = True
            sign = -1.0 if str(leg.get("action") or "") == "sell" else 1.0
            total += sign * float(raw) * float(leg.get("quantity") or 1)
        combined[key] = round(total, 6) if seen else None
    return combined


def _expected_move_strikes(ctx: BuildContext) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float | None]:
    """Strike A = spot + ATM straddle, Strike B = spot − ATM straddle, nearest listed strikes."""
    atm_call = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    if atm_call is None:
        return None, None, None
    atm_put = contract_at_strike(ctx.contracts, "put", float(atm_call["strike"]))
    call_mid = mid(atm_call)
    put_mid = mid(atm_put) if atm_put else None
    if call_mid is None or put_mid is None:
        return None, None, None
    move = float(call_mid) + float(put_mid)
    calls = [c for c in ctx.contracts if c.get("side") == "call" and c.get("strike") is not None]
    puts = [c for c in ctx.contracts if c.get("side") == "put" and c.get("strike") is not None]
    if not calls or not puts:
        return None, None, move
    front_call = min(calls, key=lambda c: (abs(float(c["strike"]) - (ctx.spot + move)), float(c["strike"])))
    front_put = min(puts, key=lambda c: (abs(float(c["strike"]) - (ctx.spot - move)), float(c["strike"])))
    return front_call, front_put, move


def _build_apex(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.strategies.validator import apex_structure_reason

    front_call, front_put, expected_move = _expected_move_strikes(ctx)
    if front_call is None or front_put is None:
        return _blocked(
            ctx,
            "Expected move is missing because the front-week at-the-money straddle is not on the chain.",
        )
    back_call = contract_at_strike(ctx.back_month_contracts, "call", float(front_call["strike"])) if front_call else None
    back_put = contract_at_strike(ctx.back_month_contracts, "put", float(front_put["strike"])) if front_put else None
    missing: list[str] = []
    if front_call is None:
        missing.append("front-week call")
    if front_put is None:
        missing.append("front-week put")
    if front_call is not None and back_call is None:
        missing.append("back-week call at the same strike")
    if front_put is not None and back_put is None:
        missing.append("back-week put at the same strike")
    plan = [
        ("buy", back_call, ctx.back_expiry),
        ("buy", back_put, ctx.back_expiry),
        ("sell", front_call, ctx.front_expiry),
        ("sell", front_put, ctx.front_expiry),
    ]
    legs: list[dict[str, Any]] = []
    for action, contract, exp in plan:
        if contract is None:
            continue
        leg = make_option_leg(action, contract, expiry=exp)
        if not leg or not leg.get("symbol"):
            missing.append(f"{action} {contract.get('side')} OCC symbol")
            continue
        _copy_greeks(leg, contract)
        leg["order_type"] = "market"
        legs.append(leg)
    if missing or len(legs) != 4:
        reason = apex_structure_reason(legs, missing=missing or ["a complete four-leg quote"])
        return _blocked(ctx, reason or "APEX Strategy requires all four legs.")
    reason = apex_structure_reason(legs, spot=ctx.spot)
    if reason:
        return _blocked(ctx, reason)
    net, nt = net_debit_credit(legs)
    cs = float(front_call["strike"]) if front_call else ctx.spot
    ps = float(front_put["strike"]) if front_put else ctx.spot
    fd = dte_from_expiry(ctx.front_expiry) or 7
    bd = dte_from_expiry(ctx.back_expiry) or fd + 14

    def _leg_iv(contract: dict[str, Any] | None) -> float | None:
        if not contract:
            return None
        raw = contract.get("iv")
        return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None

    post_event_iv = ctx.hv if ctx.hv and ctx.hv > 0 else None
    payoff = invoke_payoff(
        "payoff_apex_strategy",
        spot=ctx.spot,
        call_strike=cs,
        put_strike=ps,
        net_debit=net,
        front_dte_days=fd,
        back_dte_days=bd,
        iv=ctx.iv,
        back_call_iv=_leg_iv(back_call),
        back_put_iv=_leg_iv(back_put),
        contract_multiplier=ctx.contract_multiplier,
        post_event_iv=post_event_iv,
        expected_move=expected_move,
    )
    spec = STRATEGY_REGISTRY["apex_strategy"]
    metrics = _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)
    metrics["greeks"] = _combined_greeks(metrics.get("legs") or legs)
    metrics["capital_required"] = metrics.get("max_loss")
    metrics["max_loss_unlimited_allowed"] = False
    metrics["payoff_depends_on_remaining_leg"] = False
    front_prem = sum(float(lg.get("mid") or 0) for lg in legs if lg.get("action") == "sell")
    back_prem = sum(float(lg.get("mid") or 0) for lg in legs if lg.get("action") == "buy")
    if back_prem > 0:
        offset = front_prem / back_prem
        metrics["premium_offset_pct"] = round(offset * 100.0, 2)
        offset_note = f"Front-week premium offsets {offset * 100:.1f}% of the back-week premium on this chain."
    else:
        offset_note = "Front-week premium offset could not be measured on this chain."
    notes = str(metrics.get("payoff_notes") or "")
    metrics["payoff_notes"] = f"{notes} {offset_note}".strip()
    metrics["notes"] = metrics["payoff_notes"]
    if expected_move is not None:
        metrics["expected_move"] = round(float(expected_move), 4)
    return metrics.get("legs") or legs, metrics


def _build_leaps_long(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    found = _leaps_pool(ctx)
    if found is None:
        return _blocked(
            ctx,
            "A LEAPS contract is more than a year out, and this chain has no expiration beyond one year.",
        )
    expiry, pool = found
    contract = nearest_strike_contract(pool, side, ctx.spot)
    leg = make_option_leg("buy", contract, expiry=expiry)
    if not leg or (dte_from_expiry(str(leg.get("expiry") or "")) or 0) <= LEAPS_MIN_DTE:
        return _blocked(
            ctx,
            "A LEAPS contract is more than a year out, and this chain has no expiration beyond one year.",
        )
    legs = [leg]
    prem = leg.get("mid") or 0
    strike = float(leg.get("strike") or ctx.spot)
    payoff = invoke_payoff("payoff_long_option", premium=prem, strike=strike, side=side, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_call_leaps"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_leaps_straddle(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    found = _leaps_pool(ctx)
    if found is None:
        return _blocked(
            ctx,
            "A LEAPS straddle needs a call and a put expiring more than a year out. This chain has no expiration beyond one year.",
        )
    expiry, pool = found
    call_c = nearest_strike_contract(pool, "call", ctx.spot)
    if call_c is None:
        return _blocked(
            ctx,
            "A LEAPS straddle needs a call and a put expiring more than a year out. This chain has no call that far out.",
        )
    strike = float(call_c["strike"])
    put_c = contract_at_strike(pool, "put", strike)
    legs = [lg for lg in [make_option_leg("buy", call_c, expiry=expiry), make_option_leg("buy", put_c, expiry=expiry)] if lg]
    if len(legs) != 2 or any((dte_from_expiry(str(lg.get("expiry") or "")) or 0) <= LEAPS_MIN_DTE for lg in legs):
        return _blocked(
            ctx,
            "A LEAPS straddle needs a call and a put expiring more than a year out. This chain has no expiration beyond one year.",
        )
    cm = legs[0].get("mid") or 0
    pm = legs[1].get("mid") or 0
    payoff = invoke_payoff("payoff_long_straddle", call_premium=cm, put_premium=pm, strike=strike, contract_multiplier=ctx.contract_multiplier)
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["long_straddle_leaps"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_deep_itm(ctx: BuildContext, side: Side) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _deep_itm_contract(ctx.contracts, side, ctx.spot)
    if contract is None and ctx.back_month_contracts:
        contract = _deep_itm_contract(ctx.back_month_contracts, side, ctx.spot)
    if contract is None:
        return _blocked(
            ctx,
            "Deep ITM requires a strike at least 10% in the money. This chain has no such contract, so an at-the-money option was not used.",
        )
    expiry = str(contract.get("expiry") or ctx.front_expiry or "")
    leg = make_option_leg("buy", contract, expiry=expiry or None)
    if not leg:
        return _blocked(ctx, "Deep ITM requires a strike at least 10% in the money. The quote could not be built.")
    strike = float(leg["strike"])
    if side == "call" and strike > ctx.spot * (1.0 - DEEP_ITM_FRACTION) + 1e-6:
        return _blocked(ctx, "Deep ITM requires a call strike at least 10% below spot. The selected strike is not deep in the money.")
    if side == "put" and strike < ctx.spot * (1.0 + DEEP_ITM_FRACTION) - 1e-6:
        return _blocked(ctx, "Deep ITM requires a put strike at least 10% above spot. The selected strike is not deep in the money.")
    legs = [leg]
    payoff = invoke_payoff(
        "payoff_long_option",
        premium=leg.get("mid") or 0,
        strike=strike,
        side=side,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["deep_itm_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_synthetic_call(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Long stock plus a long put. This is not a long call and a short put."""
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    put_c = nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    put_leg = make_option_leg("buy", put_c, expiry=ctx.front_expiry)
    if not put_leg:
        return _blocked(ctx, "A synthetic call is long stock plus a long put. This chain has no put.")
    legs = [stock, put_leg]
    payoff = invoke_payoff(
        "payoff_protective_put",
        stock_cost=ctx.spot,
        put_strike=float(put_leg["strike"]),
        put_premium=put_leg.get("mid") or 0,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["synthetic_call"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_synthetic_put(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Short stock plus a long call. This is not a long put and a short call."""
    stock = make_stock_leg("sell", ctx.spot, ctx.ticker)
    call_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    call_leg = make_option_leg("buy", call_c, expiry=ctx.front_expiry)
    if not call_leg:
        return _blocked(ctx, "A synthetic put is short stock plus a long call. This chain has no call.")
    legs = [stock, call_leg]
    payoff = invoke_payoff(
        "payoff_synthetic_put",
        stock_short_price=ctx.spot,
        call_strike=float(call_leg["strike"]),
        call_premium=call_leg.get("mid") or 0,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["synthetic_put"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_synthetic_straddle(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Long stock plus two long puts. This is not an option straddle."""
    stock = make_stock_leg("buy", ctx.spot, ctx.ticker)
    put_c = nearest_strike_contract(ctx.contracts, "put", ctx.spot)
    put_leg = make_option_leg("buy", put_c, expiry=ctx.front_expiry, quantity=2)
    if not put_leg:
        return _blocked(ctx, "A synthetic straddle is long stock plus two long puts. This chain has no put.")
    legs = [stock, put_leg]
    payoff = invoke_payoff(
        "payoff_synthetic_straddle",
        stock_price=ctx.spot,
        put_strike=float(put_leg["strike"]),
        put_premium=put_leg.get("mid") or 0,
        put_quantity=2,
        contract_multiplier=ctx.contract_multiplier,
    )
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["synthetic_straddle"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_wheel(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cash-secured short put, or the covered call only when shares are already held."""
    if ctx.shares_held >= ctx.contract_multiplier:
        call_c = _otm_contract(ctx.contracts, "call", ctx.spot)
        call_leg = make_option_leg("sell", call_c, expiry=ctx.front_expiry)
        if not call_leg:
            return _blocked(ctx, "The covered-call stage of the wheel needs an out-of-the-money call. This chain has none.")
        stock = make_stock_leg("buy", ctx.spot, ctx.ticker, quantity=ctx.contract_multiplier)
        stock["already_held"] = True
        stock["order_qty"] = 0
        stock["shares_used"] = ctx.contract_multiplier
        legs = [stock, call_leg]
        prem = call_leg.get("mid") or 0
        payoff = invoke_payoff(
            "payoff_covered_call",
            stock_cost=ctx.spot,
            call_strike=float(call_leg["strike"]),
            call_premium=prem,
            contract_multiplier=ctx.contract_multiplier,
        )
        payoff["payoff_notes"] = (
            "Covered-call stage of the wheel. Shares are already held, so the short call is covered. "
            "The cash-secured put is the opening stage and is not added while those shares are held."
        )
        net, nt = net_debit_credit(legs)
        spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["wheel_strategy"]
        return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)

    put_c = _otm_contract(ctx.contracts, "put", ctx.spot) or pick_strike(ctx.contracts, "put", ctx.spot, 0.20)
    put_leg = make_option_leg("sell", put_c, expiry=ctx.front_expiry)
    if not put_leg:
        return _blocked(ctx, "The wheel opens as a cash-secured short put. This chain has no put.")
    legs = [put_leg]
    prem = put_leg.get("mid") or 0
    strike = float(put_leg.get("strike") or ctx.spot)
    payoff = invoke_payoff("payoff_short_option", premium=prem, strike=strike, side="put", contract_multiplier=ctx.contract_multiplier)
    payoff["payoff_notes"] = (
        "Cash-secured short put, the opening stage of the wheel. Cash covers assignment. "
        "The covered-call stage is not included because shares are not already held."
    )
    payoff["max_loss_unlimited_allowed"] = False
    payoff["max_profit_unlimited_allowed"] = False
    net, nt = net_debit_credit(legs)
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["wheel_strategy"]
    return legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)


def _build_vega_neutral(ctx: BuildContext) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Same strike across two expirations, sized so vega cancels. Not a vertical."""
    if not ctx.back_month_contracts or not ctx.back_expiry or ctx.back_expiry == ctx.front_expiry:
        return _blocked(
            ctx,
            "Vega-neutral needs offsetting vegas across two expirations. This chain has one expiration, so a vertical was not built.",
        )
    front_c = nearest_strike_contract(ctx.contracts, "call", ctx.spot)
    if front_c is None:
        return _blocked(ctx, "Vega-neutral needs an at-the-money call on the nearer expiration. This chain has no call.")
    strike = float(front_c["strike"])
    back_c = contract_at_strike(ctx.back_month_contracts, "call", strike)
    if back_c is None:
        return _blocked(
            ctx,
            "Vega-neutral needs the same call strike on a later expiration. That strike is missing, so a vertical was not built.",
        )
    front_expiry = str(front_c.get("expiry") or ctx.front_expiry or "")
    back_expiry = str(back_c.get("expiry") or ctx.back_expiry or "")
    if not front_expiry or front_expiry == back_expiry:
        return _blocked(
            ctx,
            "Vega-neutral needs two expirations. Both calls share one expiration, so a vertical was not built.",
        )
    front_vega = _contract_vega(front_c, spot=ctx.spot, expiry=front_expiry, iv_fallback=ctx.iv)
    back_vega = _contract_vega(back_c, spot=ctx.spot, expiry=back_expiry, iv_fallback=ctx.iv)
    if front_vega is None or back_vega is None:
        return _blocked(
            ctx,
            "Vega-neutral needs a vega on each expiration. This chain does not support that, so a vertical was not built.",
        )
    quantities = _vega_quantities(front_vega, back_vega)
    if quantities is None:
        return _blocked(
            ctx,
            "Vega-neutral needs quantities that offset the two vegas. No small ratio does that on this chain, so a vertical was not built.",
        )
    front_qty, back_qty = quantities
    front_leg = make_option_leg("buy", front_c, expiry=front_expiry, quantity=front_qty)
    back_leg = make_option_leg("sell", back_c, expiry=back_expiry, quantity=back_qty)
    legs = [lg for lg in [front_leg, back_leg] if lg]
    if len(legs) != 2 or legs[0].get("strike") != legs[1].get("strike") or legs[0].get("expiry") == legs[1].get("expiry"):
        return _blocked(ctx, "Vega-neutral was not built because the two calls are not the same strike in two expirations.")
    net, nt = net_debit_credit(legs)
    payoff = {
        "max_profit": None,
        "max_loss": None,
        "breakevens": [],
        "max_profit_unlimited_allowed": False,
        "max_loss_unlimited_allowed": False,
        "payoff_notes": (
            f"Buy {front_qty} nearer call and sell {back_qty} later call at the same strike so the vegas offset. "
            "No closed-form max profit is shown."
        ),
    }
    spec = get_strategy_spec(ctx.strategy_id) or STRATEGY_REGISTRY["vega_neutral_spread"]
    _, metrics = legs, _finalize(spec, legs, payoff, net, nt, ctx.contract_multiplier)
    metrics["vega_offset"] = {
        "front_vega": round(front_vega, 6),
        "back_vega": round(back_vega, 6),
        "front_quantity": front_qty,
        "back_quantity": back_qty,
    }
    return legs, _without_closed_form(metrics)


# strategy_id → builder
BUILDERS: dict[str, Any] = {
    "long_call": lambda c: _build_single_long(c, "call"),
    "long_put": lambda c: _build_single_long(c, "put"),
    "naked_call": lambda c: _build_single_short(c, "call"),
    "naked_put": lambda c: _build_single_short(c, "put"),
    "apex_benchmark_greeks_strategy": lambda c: _build_benchmark(c),
    "long_call_leaps": lambda c: _build_leaps_long(c, "call"),
    "long_put_leaps": lambda c: _build_leaps_long(c, "put"),
    "deep_itm_call": lambda c: _build_deep_itm(c, "call"),
    "deep_itm_put": lambda c: _build_deep_itm(c, "put"),
    "atm_call": lambda c: _build_single_long(c, "call"),
    "vix_call_hedge": lambda c: _build_single_long(c, "call"),
    "wheel_strategy": _build_wheel,
    "bull_call_spread": lambda c: _build_vertical_debit(c, "call"),
    "bear_put_spread": lambda c: _build_vertical_debit(c, "put"),
    "call_debit_spread": lambda c: _build_vertical_debit(c, "call"),
    "put_debit_spread": lambda c: _build_vertical_debit(c, "put"),
    "wide_bull_call_spread": lambda c: _build_vertical_debit(c, "call", wide=True),
    "wide_bear_put_spread": lambda c: _build_vertical_debit(c, "put", wide=True),
    "vega_neutral_spread": _build_vega_neutral,
    "bull_put_spread_credit": lambda c: _build_vertical_credit(c, "put"),
    "bear_call_spread_credit": lambda c: _build_vertical_credit(c, "call"),
    "call_credit_spread": lambda c: _build_vertical_credit(c, "call"),
    "put_credit_spread": lambda c: _build_vertical_credit(c, "put"),
    "long_straddle": lambda c: _build_straddle(c),
    "long_straddle_leaps": _build_leaps_straddle,
    "earnings_straddle": lambda c: _build_straddle(c),
    "long_straddle_pre_earnings": lambda c: _build_straddle(c),
    "gamma_scalping": lambda c: _build_straddle(c),
    "synthetic_straddle": _build_synthetic_straddle,
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
    "double_diagonal": _build_double_diagonal,
    "short_iron_condor": lambda c: _build_iron_condor(c),
    "iv_crush_short_iron_condor": lambda c: _build_iron_condor(c),
    "theta_harvest_iron_condor": lambda c: _build_iron_condor(c),
    "iron_condor_monthly": lambda c: _build_iron_condor(c),
    "iron_condor_wide": lambda c: _build_iron_condor(c, wide=True),
    "long_iron_condor": lambda c: _build_iron_condor(c, long=True),
    "reverse_iron_condor": lambda c: _build_iron_condor(c, long=True),
    "long_call_butterfly": lambda c: _build_butterfly(c, "call"),
    "long_put_butterfly": lambda c: _build_butterfly(c, "put"),
    "short_call_butterfly": lambda c: _build_butterfly(c, "call", short=True),
    "short_put_butterfly": lambda c: _build_butterfly(c, "put", short=True),
    "iron_butterfly": lambda c: _build_iron_butterfly(c),
    "long_iron_butterfly": lambda c: _build_iron_butterfly(c, long=True),
    "short_iron_butterfly_variant": lambda c: _build_iron_butterfly(c),
    "broken_wing_butterfly": lambda c: _build_butterfly(c, "call", broken=True),
    "skip_strike_butterfly": lambda c: _build_butterfly(c, "call", broken=True),
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
    "married_put": _build_stock_long_put,
    "leveraged_covered_call": _build_leveraged_covered_call,
    "stock_long_put": _build_stock_long_put,
    "protective_collar": _build_collar,
    "collar": _build_collar,
    "synthetic_long_stock": lambda c: _build_synthetic(c, long=True),
    "synthetic_short_stock": lambda c: _build_synthetic(c, long=False),
    "synthetic_call": _build_synthetic_call,
    "synthetic_put": _build_synthetic_put,
    "long_combo": lambda c: _build_synthetic(c, long=True),
    "short_combo": lambda c: _build_synthetic(c, long=False),
    "conversion": _build_conversion,
    "reversal": _build_reversal,
    "box_spread": _build_box_spread,
    "risk_reversal": _build_risk_reversal,
    "volatility_skew_trade": _build_risk_reversal,
    "dispersion_trade": _build_dispersion,
    "apex_strategy": _build_apex,
    "jelly_roll": _build_jelly_roll,
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
    shares_held: int = 0,
    shares_encumbered: int = 0,
    shares_short: int = 0,
    share_avg_cost: float | None = None,
    stock_ask: float | None = None,
    component_contracts: list[dict[str, Any]] | None = None,
    component_ticker: str | None = None,
    hv: float | None = None,
) -> dict[str, Any] | None:
    from app.services.stock_leg import apply_equity_holdings, multiplier_from_contracts

    spec = STRATEGY_REGISTRY.get(strategy_id)
    if not spec or spec.leg_count == 0:
        return None
    if not contracts or spot is None:
        return _empty_metrics(contract_multiplier)

    resolved_multiplier = multiplier_from_contracts(contracts, explicit=contract_multiplier)
    ctx = BuildContext(
        strategy_id=strategy_id,
        spot=float(spot),
        contracts=contracts,
        back_month_contracts=back_month_contracts or [],
        front_expiry=front_expiry,
        back_expiry=back_expiry,
        iv=iv if iv and iv > 0 else 0.25,
        ticker=ticker or "SYM",
        contract_multiplier=resolved_multiplier,
        recommended=recommended,
        shares_held=int(shares_held or 0),
        shares_encumbered=int(shares_encumbered or 0),
        shares_short=int(shares_short or 0),
        share_avg_cost=share_avg_cost,
        stock_ask=stock_ask,
        component_contracts=component_contracts,
        component_ticker=component_ticker,
        hv=hv,
    )

    builder = BUILDERS.get(strategy_id)
    if not builder:
        return None

    _, metrics = builder(ctx)
    return apply_equity_holdings(
        spec,
        metrics,
        ticker=ctx.ticker,
        spot=ctx.spot,
        multiplier=ctx.contract_multiplier,
        shares_held=ctx.shares_held,
        shares_encumbered=ctx.shares_encumbered,
        shares_short=ctx.shares_short,
        avg_cost=ctx.share_avg_cost,
        ask=ctx.stock_ask,
        contracts=1,
    )


def from_display_name(
    strategy_name: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    from app.strategies.registry import resolve_strategy_id

    sid = resolve_strategy_id(strategy_name)
    if not sid:
        return None
    return build_registry_metrics(sid, **kwargs)
