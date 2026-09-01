"""Shared payoff calculation utilities."""

from __future__ import annotations

import math
from typing import Any, Callable, Literal

from app.analysis import black_scholes as bs

Side = Literal["call", "put"]


def scan_payoff(
    payoff_fn: Callable[[float], float],
    *,
    center: float,
    span: float,
    steps: int = 400,
) -> tuple[float, float]:
    lo = max(center - span, 0.01)
    hi = center + span
    step = (hi - lo) / steps
    values = [payoff_fn(lo + step * i) for i in range(steps + 1)]
    return min(values), max(values)


def find_breakeven_range(
    payoff_fn: Callable[[float], float],
    *,
    center: float,
    span: float,
    steps: int = 800,
    tolerance: float = 0.5,
) -> list[float]:
    lo = max(center - span, 0.01)
    hi = center + span
    step = (hi - lo) / steps
    points: list[tuple[float, float]] = []
    for i in range(steps + 1):
        s = lo + step * i
        points.append((s, payoff_fn(s)))

    roots: list[float] = []
    for i in range(len(points) - 1):
        s0, p0 = points[i]
        s1, p1 = points[i + 1]
        if abs(p0) <= tolerance:
            roots.append(round(s0, 2))
            continue
        if p0 * p1 < 0:
            t = abs(p0) / (abs(p0) + abs(p1))
            root = s0 + t * (s1 - s0)
            roots.append(round(root, 2))

    if not roots:
        return []
    roots.sort()
    deduped: list[float] = []
    for r in roots:
        if not deduped or abs(r - deduped[-1]) > 0.05:
            deduped.append(r)
    if len(deduped) >= 2:
        return [deduped[0], deduped[-1]]
    return deduped


def find_breakeven_roots(
    payoff_fn: Callable[[float], float],
    *,
    center: float,
    span: float,
    steps: int = 800,
    tolerance: float = 0.5,
) -> list[float]:
    """Return all breakeven roots (for dual-breakeven strategies)."""
    lo = max(center - span, 0.01)
    hi = center + span
    step = (hi - lo) / steps
    points: list[tuple[float, float]] = []
    for i in range(steps + 1):
        s = lo + step * i
        points.append((s, payoff_fn(s)))

    roots: list[float] = []
    for i in range(len(points) - 1):
        s0, p0 = points[i]
        s1, p1 = points[i + 1]
        if abs(p0) <= tolerance:
            roots.append(round(s0, 2))
            continue
        if p0 * p1 < 0:
            t = abs(p0) / (abs(p0) + abs(p1))
            roots.append(round(s0 + t * (s1 - s0), 2))

    roots.sort()
    deduped: list[float] = []
    for r in roots:
        if not deduped or abs(r - deduped[-1]) > 0.05:
            deduped.append(r)
    return deduped


def intrinsic(side: Side, strike: float, underlying: float) -> float:
    if side == "call":
        return max(underlying - strike, 0.0)
    return max(strike - underlying, 0.0)


def leg_pnl(
    *,
    action: str,
    side: Side | str,
    strike: float,
    premium: float,
    underlying: float,
    quantity: int = 1,
    contract_multiplier: int = 100,
) -> float:
    if side == "stock":
        if action == "buy":
            return (underlying - premium) * quantity
        return (premium - underlying) * quantity
    intr = intrinsic(side, strike, underlying)  # type: ignore[arg-type]
    if action == "buy":
        return (intr - premium) * quantity * contract_multiplier
    return (premium - intr) * quantity * contract_multiplier


def multi_leg_payoff_at_expiry(
    legs: list[dict[str, Any]],
    underlying: float,
    *,
    contract_multiplier: int = 100,
) -> float:
    total = 0.0
    for leg in legs:
        qty = int(leg.get("quantity") or 1)
        prem = float(leg.get("mid") or leg.get("premium") or 0)
        strike = float(leg.get("strike") or 0)
        total += leg_pnl(
            action=str(leg.get("action") or "buy"),
            side=str(leg.get("side") or "call"),
            strike=strike,
            premium=prem,
            underlying=underlying,
            quantity=qty,
            contract_multiplier=contract_multiplier,
        )
    return total


def scan_multi_leg_payoff(
    legs: list[dict[str, Any]],
    *,
    spot: float,
    contract_multiplier: int = 100,
    span_factor: float = 0.35,
) -> tuple[float, float, list[float]]:
    strikes = [float(l["strike"]) for l in legs if l.get("strike") is not None]
    center = spot
    span = max(spot * span_factor, max(strikes, default=spot) * 0.25, 10.0)

    def pnl(u: float) -> float:
        return multi_leg_payoff_at_expiry(legs, u, contract_multiplier=contract_multiplier)

    max_loss, max_profit = scan_payoff(pnl, center=center, span=span)
    bes = find_breakeven_roots(pnl, center=center, span=span)
    return max_loss, max_profit, bes


def calendar_pnl_at_front_expiry(
    *,
    spot: float,
    strike: float,
    net_debit: float,
    front_dte_days: int,
    back_dte_days: int,
    iv: float,
    side: Side,
    contract_multiplier: int = 100,
) -> Callable[[float], float]:
    remaining_dte = max(back_dte_days - front_dte_days, 1)
    years_remaining = bs.year_fraction(remaining_dte)
    vol = max(iv, 0.08)

    def pnl_at_front_expiry(underlying: float) -> float:
        short_intr = intrinsic(side, strike, underlying)
        g = bs.greeks(spot=underlying, strike=strike, years=years_remaining, vol=vol, side=side)
        back_value = g.price if g else 0.0
        return (back_value - short_intr - net_debit) * contract_multiplier

    return pnl_at_front_expiry
