"""Closed-form payoff math for structures with a documented expiry formula.

Money is computed with Decimal. Outputs are quantized to cents. Structures
without a closed form (calendars, diagonals, butterflies, ratios, and the rest
of the registry) are left to their existing handlers — this module returns None
for those legs.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.strategies.registry import StrategySpec

_CENT = Decimal("0.01")
_GRID_TOLERANCE = Decimal("0.01")

# Payoff refs whose expiry value is a closed form in payoffs/core.py.
DOCUMENTED_PAYOFF_REFS: frozenset[str] = frozenset(
    {
        "payoff_vertical_debit",
        "payoff_vertical_credit",
        "payoff_iron_condor",
        "payoff_long_iron_condor",
        "payoff_long_option",
    }
)

# Butterflies, ratios, and other structures without a front-expiry model.
# Calendars and diagonals publish the numeric grid instead.
NO_CLOSED_FORM_PAYOFF_REFS: frozenset[str] = frozenset(
    {
        "payoff_butterfly",
        "payoff_short_butterfly",
        "payoff_broken_wing_butterfly",
        "payoff_iron_butterfly",
        "payoff_long_iron_butterfly",
        "payoff_multi_leg_scan",
        "payoff_christmas_tree",
        "payoff_jelly_roll",
        "payoff_pmcc",
        "payoff_dispersion",
    }
)

REMAINING_LONG_LEG_NOTE = (
    "Payoff depends on the remaining long leg. No closed-form max profit is shown."
)


def money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not number.is_finite():
            return None
        return number
    return None


def _option_legs(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leg in legs:
        side = leg.get("side")
        action = leg.get("action")
        if side not in {"call", "put"} or action not in {"buy", "sell"}:
            continue
        strike = to_decimal(leg.get("strike"))
        mid = to_decimal(leg.get("mid"))
        if strike is None or mid is None:
            continue
        rows.append({**leg, "strike": strike, "mid": mid, "side": side, "action": action})
    return rows


def net_from_mids(legs: list[dict[str, Any]]) -> tuple[Decimal, str]:
    """Signed net from leg mids. Positive is a debit paid."""
    signed = Decimal(0)
    for leg in _option_legs(legs):
        qty = to_decimal(leg.get("quantity")) or Decimal(1)
        premium = leg["mid"] * qty
        if leg["action"] == "buy":
            signed += premium
        else:
            signed -= premium
    kind = "debit" if signed >= 0 else "credit"
    return signed, kind


def expiry_pnl(
    legs: list[dict[str, Any]],
    underlying: Decimal | int | float | str,
    *,
    contract_multiplier: int = 100,
) -> Decimal:
    """Expiry P&L in dollars from intrinsic value. Positive is a gain."""
    spot = to_decimal(underlying)
    if spot is None:
        return Decimal(0)
    mult = Decimal(contract_multiplier)
    total = Decimal(0)
    for leg in _option_legs(legs):
        strike = leg["strike"]
        if leg["side"] == "call":
            intrinsic = max(spot - strike, Decimal(0))
        else:
            intrinsic = max(strike - spot, Decimal(0))
        qty = to_decimal(leg.get("quantity")) or Decimal(1)
        per = (intrinsic - leg["mid"]) if leg["action"] == "buy" else (leg["mid"] - intrinsic)
        total += per * qty * mult
    return total


def _vertical_quote(
    legs: list[dict[str, Any]],
    *,
    contract_multiplier: int,
    credit: bool,
) -> dict[str, Any] | None:
    rows = _option_legs(legs)
    if len(rows) != 2:
        return None
    if rows[0]["side"] != rows[1]["side"]:
        return None
    side = rows[0]["side"]
    buy = next((leg for leg in rows if leg["action"] == "buy"), None)
    sell = next((leg for leg in rows if leg["action"] == "sell"), None)
    if buy is None or sell is None or buy["strike"] == sell["strike"]:
        return None
    signed, kind = net_from_mids(rows)
    width = abs(sell["strike"] - buy["strike"])
    mult = Decimal(contract_multiplier)
    if credit:
        if kind != "credit":
            return None
        net_credit = -signed
        long_strike = buy["strike"]
        short_strike = sell["strike"]
        if side == "put" and not (short_strike > long_strike):
            return None
        if side == "call" and not (long_strike > short_strike):
            return None
        max_profit = money(net_credit * mult)
        max_loss = money((width - net_credit) * mult)
        be = short_strike - net_credit if side == "put" else short_strike + net_credit
        return {
            "structure": "vertical_credit",
            "net_debit_credit": money(net_credit),
            "net_type": "credit",
            "max_profit": max_profit,
            "max_loss": max_loss,
            "max_profit_unlimited": False,
            "max_loss_unlimited": False,
            "breakevens": [money(be)],
        }
    if kind != "debit":
        return None
    net_debit = signed
    if side == "call" and not (sell["strike"] > buy["strike"]):
        return None
    if side == "put" and not (buy["strike"] > sell["strike"]):
        return None
    max_loss = money(net_debit * mult)
    max_profit = money((width - net_debit) * mult)
    be = buy["strike"] + net_debit if side == "call" else buy["strike"] - net_debit
    return {
        "structure": "vertical_debit",
        "net_debit_credit": money(net_debit),
        "net_type": "debit",
        "max_profit": max_profit,
        "max_loss": max_loss,
        "max_profit_unlimited": False,
        "max_loss_unlimited": False,
        "breakevens": [money(be)],
    }


def _iron_condor_quote(
    legs: list[dict[str, Any]],
    *,
    contract_multiplier: int,
    long: bool,
) -> dict[str, Any] | None:
    rows = _option_legs(legs)
    puts = [leg for leg in rows if leg["side"] == "put"]
    calls = [leg for leg in rows if leg["side"] == "call"]
    if len(puts) != 2 or len(calls) != 2:
        return None
    short_put = next((leg for leg in puts if leg["action"] == "sell"), None)
    long_put = next((leg for leg in puts if leg["action"] == "buy"), None)
    short_call = next((leg for leg in calls if leg["action"] == "sell"), None)
    long_call = next((leg for leg in calls if leg["action"] == "buy"), None)
    if not all((short_put, long_put, short_call, long_call)):
        return None
    assert short_put and long_put and short_call and long_call
    signed, kind = net_from_mids(rows)
    mult = Decimal(contract_multiplier)
    if long:
        put_width = long_put["strike"] - short_put["strike"]
        call_width = short_call["strike"] - long_call["strike"]
        if put_width <= 0 or call_width <= 0 or kind != "debit":
            return None
        net_debit = signed
        width = max(put_width, call_width)
        return {
            "structure": "long_iron_condor",
            "net_debit_credit": money(net_debit),
            "net_type": "debit",
            "max_profit": money((width - net_debit) * mult),
            "max_loss": money(net_debit * mult),
            "max_profit_unlimited": False,
            "max_loss_unlimited": False,
            "breakevens": [money(long_put["strike"] + net_debit), money(long_call["strike"] - net_debit)],
        }
    put_width = short_put["strike"] - long_put["strike"]
    call_width = long_call["strike"] - short_call["strike"]
    if put_width <= 0 or call_width <= 0 or kind != "credit":
        return None
    net_credit = -signed
    width = max(put_width, call_width)
    return {
        "structure": "iron_condor",
        "net_debit_credit": money(net_credit),
        "net_type": "credit",
        "max_profit": money(net_credit * mult),
        "max_loss": money((width - net_credit) * mult),
        "max_profit_unlimited": False,
        "max_loss_unlimited": False,
        "breakevens": [
            money(short_put["strike"] - net_credit),
            money(short_call["strike"] + net_credit),
        ],
    }


def _long_option_quote(legs: list[dict[str, Any]], *, contract_multiplier: int) -> dict[str, Any] | None:
    rows = _option_legs(legs)
    if len(rows) != 1 or rows[0]["action"] != "buy":
        return None
    leg = rows[0]
    premium = leg["mid"]
    mult = Decimal(contract_multiplier)
    strike = leg["strike"]
    max_loss = money(premium * mult)
    if leg["side"] == "call":
        return {
            "structure": "long_call",
            "net_debit_credit": money(premium),
            "net_type": "debit",
            "max_profit": None,
            "max_loss": max_loss,
            "max_profit_unlimited": True,
            "max_loss_unlimited": False,
            "breakevens": [money(strike + premium)],
        }
    # Long put: loss is the premium; profit is capped because the underlying cannot trade below zero.
    return {
        "structure": "long_put",
        "net_debit_credit": money(premium),
        "net_type": "debit",
        "max_profit": money((strike - premium) * mult),
        "max_loss": max_loss,
        "max_profit_unlimited": False,
        "max_loss_unlimited": False,
        "breakevens": [money(strike - premium)],
    }


def quote_documented_structure(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    *,
    contract_multiplier: int = 100,
) -> dict[str, Any] | None:
    """Return closed-form payoff fields, or None when this structure has no formula here."""
    if spec.equity_required or spec.payoff_function_ref not in DOCUMENTED_PAYOFF_REFS:
        return None
    if any(leg.get("side") == "stock" for leg in legs):
        return None
    ref = spec.payoff_function_ref
    if ref == "payoff_vertical_debit":
        return _vertical_quote(legs, contract_multiplier=contract_multiplier, credit=False)
    if ref == "payoff_vertical_credit":
        return _vertical_quote(legs, contract_multiplier=contract_multiplier, credit=True)
    if ref == "payoff_iron_condor":
        return _iron_condor_quote(legs, contract_multiplier=contract_multiplier, long=False)
    if ref == "payoff_long_iron_condor":
        return _iron_condor_quote(legs, contract_multiplier=contract_multiplier, long=True)
    if ref == "payoff_long_option":
        return _long_option_quote(legs, contract_multiplier=contract_multiplier)
    return None


def documented_metric_overrides(quoted: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe metric fields. Unlimited sides stay null plus the existing flag."""
    overrides: dict[str, Any] = {
        "net_debit_credit": float(quoted["net_debit_credit"]),
        "net_type": quoted["net_type"],
        "breakevens": [float(be) for be in quoted["breakevens"]],
        "max_profit_unlimited_allowed": bool(quoted["max_profit_unlimited"]),
        "max_loss_unlimited_allowed": bool(quoted["max_loss_unlimited"]),
    }
    overrides["max_profit"] = None if quoted["max_profit"] is None else float(quoted["max_profit"])
    overrides["max_loss"] = None if quoted["max_loss"] is None else float(quoted["max_loss"])
    return overrides


def grid_tolerance() -> Decimal:
    return _GRID_TOLERANCE
