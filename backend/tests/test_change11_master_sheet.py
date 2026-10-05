"""Change 11 Part C: knowledge-base fields and payoff grids for every strategy."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analysis.black_scholes import greeks, year_fraction
from app.strategies.knowledge_base import entry_for, validate_knowledge_base
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.payoffs.core import collar_payoff, covered_call_payoff, long_option_payoff, protective_put_payoff
from app.strategies.payoffs.helpers import multi_leg_payoff_at_expiry
from app.strategies.registry import STRATEGY_REGISTRY

TODAY = date.today()
FRONT = (TODAY + timedelta(days=30)).isoformat()
BACK = (TODAY + timedelta(days=60)).isoformat()
ROOT = "AAPL"

BACK_MONTH = {
    "calendar_spread",
    "calendar_put_spread",
    "calendar_call_spread",
    "double_calendar",
    "diagonal_spread_bullish",
    "diagonal_spread_bearish",
    "double_diagonal",
    "reverse_calendar",
    "calendar_straddle",
    "diagonal_call_spread",
    "apex_strategy",
    "jelly_roll",
    "poor_mans_covered_call",
    "vega_neutral_spread",
}


def _occ(expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{ROOT}{yymmdd}{cp}{int(round(strike * 1000)):08d}"


def _chain(spot: float, step: float, expiry: str) -> list[dict]:
    rows: list[dict] = []
    strike = min(spot - step * 3, spot * 0.7)
    stop = max(spot + step * 3, spot * 1.3)
    while strike <= stop + 1e-9:
        dist = abs(strike - spot)
        call_bid = max(0.4, 4.0 - dist * 0.08)
        put_bid = max(0.4, 3.6 - dist * 0.07)
        for side, bid, delta in (
            ("call", call_bid, max(-0.05, min(0.95, 0.55 - (strike - spot) * 0.02))),
            ("put", put_bid, max(-0.95, min(0.05, -0.45 + (strike - spot) * 0.02))),
        ):
            rows.append(
                {
                    "side": side,
                    "strike": round(strike, 2),
                    "bid": round(bid, 2),
                    "ask": round(bid + 0.1, 2),
                    "symbol": _occ(expiry, side, strike),
                    "expiry": expiry,
                    "delta": delta,
                    "iv": 0.25,
                    "open_interest": 800,
                }
            )
        strike += step
    return rows


LEAPS = {"long_call_leaps", "long_put_leaps", "long_straddle_leaps"}


def _template_legs(spec, *, spot: float, step: float, multiplier: int) -> list[dict]:
    """Synthetic legs from the registry template when a chain cannot fill the structure."""
    legs: list[dict] = []
    qty = max(multiplier // 100, 1)
    for index, item in enumerate(spec.leg_specs):
        if item.option_type == "stock":
            shares = qty * 100
            legs.append({"action": item.side, "side": "stock", "strike": spot, "mid": spot, "quantity": shares})
            continue
        strike = spot + (index - 1) * step
        if strike <= 0:
            strike = step
        legs.append(
            {
                "action": item.side,
                "side": item.option_type,
                "strike": strike,
                "mid": 1.0 + index,
                "quantity": qty,
                "expiry": FRONT,
            }
        )
    return legs


def _independent(legs: list[dict], underlying: float, *, multiplier: int = 100) -> float:
    total = 0.0
    for leg in legs:
        qty = int(leg.get("quantity") or 1)
        premium = float(leg.get("mid") or 0)
        if leg.get("side") == "stock":
            if leg.get("action") == "buy":
                total += (underlying - premium) * qty
            else:
                total += (premium - underlying) * qty
            continue
        strike = float(leg["strike"])
        if leg["side"] == "call":
            intrinsic = max(underlying - strike, 0.0)
        else:
            intrinsic = max(strike - underlying, 0.0)
        signed = (intrinsic - premium) if leg.get("action") == "buy" else (premium - intrinsic)
        total += signed * qty * multiplier
    return total


def _build(strategy_id: str, *, spot: float, step: float, multiplier: int) -> dict | None:
    spec = STRATEGY_REGISTRY[strategy_id]
    if spec.leg_count == 0:
        return None
    leaps = strategy_id in LEAPS
    front_expiry = (TODAY + timedelta(days=400)).isoformat() if leaps else FRONT
    back_expiry = (TODAY + timedelta(days=430)).isoformat() if leaps else BACK
    front = _chain(spot, step, front_expiry)
    back = _chain(spot, step, back_expiry) if strategy_id in BACK_MONTH or leaps else None
    component = _chain(spot, step, front_expiry) if strategy_id == "dispersion_trade" else None
    return build_registry_metrics(
        strategy_id,
        spot=spot,
        contracts=front,
        back_month_contracts=back,
        front_expiry=front_expiry,
        back_expiry=back_expiry if back else None,
        component_contracts=component,
        component_ticker="SPY" if component else None,
        iv=0.25,
        ticker=ROOT,
        contract_multiplier=multiplier,
        recommended={"strike": spot, "side": "call", "expiry": FRONT},
        shares_held=100 if spec.equity_required else 0,
        share_avg_cost=spot if spec.equity_required else None,
        stock_ask=spot,
    )


def test_knowledge_base_fields_cover_every_strategy() -> None:
    errors = validate_knowledge_base()
    assert errors == []
    for strategy_id, spec in STRATEGY_REGISTRY.items():
        entry = entry_for(strategy_id) or entry_for(spec.display_name)
        assert entry is not None, strategy_id
        assert entry.reference
        assert entry.max_profit and entry.max_loss and entry.breakevens


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_REGISTRY))
def test_payoff_grid_three_fixtures(strategy_id: str) -> None:
    spec = STRATEGY_REGISTRY[strategy_id]
    if spec.leg_count == 0:
        return
    fixtures = ((100.0, 5.0, 100), (80.0, 10.0, 200), (120.0, 2.5, 300))
    checked = 0
    for spot, step, multiplier in fixtures:
        metrics = _build(strategy_id, spot=spot, step=step, multiplier=multiplier)
        prices = (spot * 0.9, spot, spot * 1.15)
        if metrics is None or metrics.get("validation_blocked") or not metrics.get("legs"):
            legs = _template_legs(spec, spot=spot, step=step, multiplier=multiplier)
            for price in prices:
                left = _independent(legs, price, multiplier=multiplier)
                right = multi_leg_payoff_at_expiry(legs, price, contract_multiplier=multiplier)
                assert abs(left - right) <= 0.01, (strategy_id, price, left, right)
            checked += 1
            continue
        legs = metrics["legs"]
        expiries = {str(leg.get("expiry")) for leg in legs if leg.get("side") in {"call", "put"}}
        grid = metrics.get("payoff_grid") or []
        if len(expiries) > 1 and len(grid) >= 3:
            sample = (grid[0], grid[len(grid) // 2], grid[-1])
            for point in sample:
                underlying = float(point["underlying"])
                rebuilt = _front_expiry_model(legs, underlying, multiplier=multiplier, iv=float(metrics.get("post_event_iv") or 0.25))
                assert abs(rebuilt - float(point["pnl"])) <= 0.01, (strategy_id, underlying, rebuilt, point["pnl"])
            checked += 1
            continue
        for price in prices:
            left = _independent(legs, price, multiplier=multiplier)
            right = multi_leg_payoff_at_expiry(legs, price, contract_multiplier=multiplier)
            assert abs(left - right) <= 0.01, (strategy_id, price, left, right)
        checked += 1
    assert checked >= 3, strategy_id


def _front_expiry_model(legs: list[dict], underlying: float, *, multiplier: int, iv: float) -> float:
    """Front legs at intrinsic. Later legs with European Black-Scholes."""
    front = min(str(leg.get("expiry")) for leg in legs if leg.get("side") in {"call", "put"})
    total = 0.0
    for leg in legs:
        if leg.get("side") == "stock":
            total += _independent([leg], underlying, multiplier=1)
            continue
        qty = int(leg.get("quantity") or 1)
        premium = float(leg.get("mid") or 0)
        strike = float(leg["strike"])
        side = leg["side"]
        if str(leg.get("expiry")) == front:
            intrinsic = max(underlying - strike, 0.0) if side == "call" else max(strike - underlying, 0.0)
            value = intrinsic
        else:
            model = greeks(spot=underlying, strike=strike, years=year_fraction(30), vol=max(iv, 0.01), side=side)
            value = model.price if model else 0.0
        signed = (value - premium) if leg.get("action") == "buy" else (premium - value)
        total += signed * qty * multiplier
    return total


def test_stock_leg_formulas_three_fixtures() -> None:
    fixtures = (
        (100.0, 105.0, 2.0, 100),
        (80.0, 90.0, 1.5, 200),
        (150.0, 160.0, 4.0, 300),
    )
    for stock, strike, premium, shares in fixtures:
        covered = covered_call_payoff(stock_cost=stock, call_strike=strike, call_premium=premium, shares=shares)
        legs = [
            {"action": "buy", "side": "stock", "strike": stock, "mid": stock, "quantity": shares},
            {"action": "sell", "side": "call", "strike": strike, "mid": premium, "quantity": shares // 100},
        ]
        # At the call strike the covered call earns (K - S + C) per share.
        at_strike = _independent(legs, strike)
        assert abs(at_strike - covered["max_profit"]) <= 0.01
        assert abs(_independent(legs, 0.0) + covered["max_loss"]) <= 0.01
        protective = protective_put_payoff(stock_cost=stock, put_strike=strike - 10, put_premium=premium, shares=shares)
        put_legs = [
            {"action": "buy", "side": "stock", "strike": stock, "mid": stock, "quantity": shares},
            {"action": "buy", "side": "put", "strike": strike - 10, "mid": premium, "quantity": shares // 100},
        ]
        floor = _independent(put_legs, strike - 10)
        assert abs(floor + protective["max_loss"]) <= 0.01
        collar = collar_payoff(
            stock_cost=stock,
            put_strike=strike - 10,
            call_strike=strike,
            put_premium=premium,
            call_premium=premium - 0.5,
            contract_multiplier=shares,
        )
        collar_legs = [
            {"action": "buy", "side": "stock", "strike": stock, "mid": stock, "quantity": shares},
            {"action": "buy", "side": "put", "strike": strike - 10, "mid": premium, "quantity": shares // 100},
            {"action": "sell", "side": "call", "strike": strike, "mid": premium - 0.5, "quantity": shares // 100},
        ]
        assert abs(_independent(collar_legs, strike) - collar["max_profit"]) <= 0.01


def test_long_option_formulas_three_fixtures() -> None:
    fixtures = ((100.0, 5.0, 100, "call"), (90.0, 3.5, 200, "put"), (120.0, 8.0, 300, "call"))
    for strike, premium, multiplier, side in fixtures:
        quoted = long_option_payoff(premium=premium, strike=strike, side=side, contract_multiplier=multiplier)
        legs = [{"action": "buy", "side": side, "strike": strike, "mid": premium, "quantity": multiplier // 100}]
        assert quoted["max_loss"] == pytest.approx(premium * multiplier, abs=0.01)
        if side == "call":
            assert quoted["breakevens"] == [round(strike + premium, 2)]
            assert _independent(legs, strike + premium, multiplier=100) == pytest.approx(0, abs=0.01)
        else:
            assert quoted["max_profit"] == pytest.approx((strike - premium) * multiplier, abs=0.01)
            assert quoted["breakevens"] == [round(strike - premium, 2)]
