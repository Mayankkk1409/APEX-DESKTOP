"""Closed-form payoff math versus a hand-built expiry grid."""

from __future__ import annotations

from decimal import Decimal

from app.services.strategy_engine import compute_strategy_metrics, strategy_decision
from app.services.strategy_recommendation import real_strategy_count
from app.strategies.registry import STRATEGY_REGISTRY, get_strategy_spec
from app.strategies.structure_math import expiry_pnl, grid_tolerance, quote_documented_structure

_MULT = 100
_TOL = grid_tolerance()


def _grid_pnl(legs: list[dict], price: str) -> Decimal:
    """Independent expiry grid: intrinsic only, no closed-form helper."""
    spot = Decimal(price)
    total = Decimal(0)
    for leg in legs:
        strike = Decimal(str(leg["strike"]))
        premium = Decimal(str(leg["mid"]))
        if leg["side"] == "call":
            intrinsic = max(spot - strike, Decimal(0))
        else:
            intrinsic = max(strike - spot, Decimal(0))
        signed = (intrinsic - premium) if leg["action"] == "buy" else (premium - intrinsic)
        total += signed * Decimal(_MULT)
    return total


def _assert_grid(quoted: dict, legs: list[dict]) -> None:
    strikes = [Decimal(str(leg["strike"])) for leg in legs]
    start = min(strikes) - Decimal(20)
    if start < 0:
        start = Decimal(0)
    stop = max(strikes) + Decimal(20)
    step = Decimal("0.25")
    prices: list[Decimal] = []
    cursor = start
    while cursor <= stop:
        prices.append(cursor)
        cursor += step
    pnls = [_grid_pnl(legs, format(price, "f")) for price in prices]
    # The module grid must agree with this one; both must agree with the formula.
    module_pnls = [expiry_pnl(legs, price, contract_multiplier=_MULT) for price in prices]
    for left, right in zip(pnls, module_pnls):
        assert abs(left - right) <= _TOL
    if quoted["max_profit"] is not None:
        assert abs(max(pnls) - quoted["max_profit"]) <= _TOL
    if quoted["max_loss"] is not None:
        assert abs(min(pnls) + quoted["max_loss"]) <= _TOL
    for be in quoted["breakevens"]:
        assert abs(_grid_pnl(legs, format(be, "f"))) <= _TOL


def test_bull_call_spread_hand_values_match_expiry_grid() -> None:
    # Buy 100 call at 3.90, sell 105 call at 1.90.
    # Debit 2.00. Width 5. Max loss 200. Max profit 300. Breakeven 102.
    legs = [
        {"action": "buy", "side": "call", "strike": "100", "mid": "3.90"},
        {"action": "sell", "side": "call", "strike": "105", "mid": "1.90"},
    ]
    spec = get_strategy_spec("Bull Call Spread")
    assert spec is not None
    quoted = quote_documented_structure(spec, legs, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["net_type"] == "debit"
    assert quoted["net_debit_credit"] == Decimal("2.00")
    assert quoted["max_loss"] == Decimal("200.00")
    assert quoted["max_profit"] == Decimal("300.00")
    assert quoted["breakevens"] == [Decimal("102.00")]
    assert quoted["max_loss"] == quoted["net_debit_credit"] * Decimal(_MULT)
    _assert_grid(quoted, legs)


def test_iron_condor_hand_values_match_expiry_grid() -> None:
    # Sell 95 put 1.50, buy 90 put 0.50, sell 105 call 1.20, buy 110 call 0.40.
    # Credit 1.80. Wing width 5. Max profit 180. Max loss 320.
    # Breakevens 93.20 and 106.80.
    legs = [
        {"action": "sell", "side": "put", "strike": "95", "mid": "1.50"},
        {"action": "buy", "side": "put", "strike": "90", "mid": "0.50"},
        {"action": "sell", "side": "call", "strike": "105", "mid": "1.20"},
        {"action": "buy", "side": "call", "strike": "110", "mid": "0.40"},
    ]
    spec = get_strategy_spec("Short Iron Condor")
    assert spec is not None
    quoted = quote_documented_structure(spec, legs, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["net_type"] == "credit"
    assert quoted["net_debit_credit"] == Decimal("1.80")
    assert quoted["max_profit"] == Decimal("180.00")
    assert quoted["max_loss"] == Decimal("320.00")
    assert quoted["breakevens"] == [Decimal("93.20"), Decimal("106.80")]
    _assert_grid(quoted, legs)


def test_chain_bull_call_max_loss_is_net_debit_times_multiplier() -> None:
    contracts = [
        {"side": "call", "strike": 100.0, "bid": 3.8, "ask": 4.0, "symbol": "C100", "expiry": "2026-07-01"},
        {"side": "call", "strike": 105.0, "bid": 1.8, "ask": 2.0, "symbol": "C105", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Bull Call Spread",
        spot=100.0,
        contracts=contracts,
        recommended={"strike": 100.0, "side": "call", "expiry": "2026-07-01"},
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["net_type"] == "debit"
    assert metrics["net_debit_credit"] == 2.0
    assert metrics["max_loss"] == 200.0
    assert metrics["max_profit"] == 300.0
    assert metrics["breakevens"] == [102.0]
    multiplier = metrics["per_contract_multiplier"]
    assert abs(metrics["max_loss"] - metrics["net_debit_credit"] * multiplier) <= 0.01


def test_chain_iron_condor_matches_hand_credit() -> None:
    contracts = [
        {"side": "put", "strike": 90.0, "delta": -0.10, "bid": 0.40, "ask": 0.60, "symbol": "P90", "expiry": "2026-07-01"},
        {"side": "put", "strike": 95.0, "delta": -0.20, "bid": 1.40, "ask": 1.60, "symbol": "P95", "expiry": "2026-07-01"},
        {"side": "call", "strike": 105.0, "delta": 0.20, "bid": 1.10, "ask": 1.30, "symbol": "C105", "expiry": "2026-07-01"},
        {"side": "call", "strike": 110.0, "delta": 0.10, "bid": 0.30, "ask": 0.50, "symbol": "C110", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Short Iron Condor",
        spot=100.0,
        contracts=contracts,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["net_type"] == "credit"
    assert metrics["net_debit_credit"] == 1.8
    assert metrics["max_profit"] == 180.0
    assert metrics["max_loss"] == 320.0
    assert metrics["breakevens"] == [93.2, 106.8]


def test_undefined_risk_loss_is_unlimited_flag_not_a_number() -> None:
    contracts = [
        {"side": "call", "strike": 105.0, "delta": 0.20, "bid": 1.10, "ask": 1.30, "symbol": "C105", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Naked Call",
        spot=100.0,
        contracts=contracts,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["max_loss"] is None
    assert metrics["max_loss_unlimited_allowed"] is True
    assert isinstance(metrics["max_profit"], (int, float))


def test_scan_evaluates_registry_and_selects_one_label() -> None:
    decision = strategy_decision(
        composite=82.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.20,
        hv=0.35,
        ivr=40.0,
        tech_score=88.0,
        confirmed_pattern_count=1,
        data_fresh=True,
    )
    assert decision.strategies_evaluated == real_strategy_count()
    assert decision.strategies_evaluated == len(STRATEGY_REGISTRY) - 2
    eligible = [c for c in decision.candidates if c.eligible]
    assert len(eligible) > 1
    assert decision.best_match in {c.name for c in eligible}
    selected = [c.name for c in eligible if c.name == decision.best_match]
    assert selected == [decision.best_match]
    missed = [c for c in decision.candidates if not c.eligible]
    assert missed
    assert all(c.gate_notes for c in missed)
    assert all(c.name not in {"Naked Call", "Naked Put", "Short Straddle", "Short Strangle"} for c in decision.candidates)
    assert any(reason.startswith("Naked Call:") for reason in decision.rejection_reasons)


def test_long_iron_condor_buys_body_and_sells_wings() -> None:
    # Buy 95 put 1.50, sell 90 put 0.50, buy 105 call 1.20, sell 110 call 0.40.
    # Debit 1.80. Wing 5. Max loss 180. Max profit 320. Breakevens 96.80 and 103.20.
    contracts = [
        {"side": "put", "strike": 90.0, "delta": -0.10, "bid": 0.40, "ask": 0.60, "symbol": "P90", "expiry": "2026-07-01"},
        {"side": "put", "strike": 95.0, "delta": -0.20, "bid": 1.40, "ask": 1.60, "symbol": "P95", "expiry": "2026-07-01"},
        {"side": "call", "strike": 105.0, "delta": 0.20, "bid": 1.10, "ask": 1.30, "symbol": "C105", "expiry": "2026-07-01"},
        {"side": "call", "strike": 110.0, "delta": 0.10, "bid": 0.30, "ask": 0.50, "symbol": "C110", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Long Iron Condor",
        spot=100.0,
        contracts=contracts,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    legs = metrics["legs"]
    bought_put = next(leg for leg in legs if leg["side"] == "put" and leg["action"] == "buy")
    sold_put = next(leg for leg in legs if leg["side"] == "put" and leg["action"] == "sell")
    bought_call = next(leg for leg in legs if leg["side"] == "call" and leg["action"] == "buy")
    sold_call = next(leg for leg in legs if leg["side"] == "call" and leg["action"] == "sell")
    assert bought_put["strike"] > sold_put["strike"]
    assert sold_call["strike"] > bought_call["strike"]
    assert metrics["net_type"] == "debit"
    assert metrics["net_debit_credit"] == 1.8
    assert metrics["max_loss"] == 180.0
    assert metrics["max_profit"] == 320.0
    assert metrics["breakevens"] == [96.8, 103.2]


def test_christmas_tree_does_not_show_a_finite_max_loss() -> None:
    contracts = [
        {"side": "call", "strike": 100.0, "delta": 0.55, "bid": 3.8, "ask": 4.0, "symbol": "C100", "expiry": "2026-07-01"},
        {"side": "call", "strike": 105.0, "delta": 0.35, "bid": 1.8, "ask": 2.0, "symbol": "C105", "expiry": "2026-07-01"},
        {"side": "call", "strike": 110.0, "delta": 0.20, "bid": 0.8, "ask": 1.0, "symbol": "C110", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Christmas Tree Spread",
        spot=100.0,
        contracts=contracts,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["max_profit"] is None
    assert metrics["max_profit_unlimited_allowed"] is not True
    assert metrics["max_loss"] is None
    assert metrics["max_loss_unlimited_allowed"] is True


def test_guts_use_in_the_money_strikes() -> None:
    contracts = [
        {"side": "call", "strike": 95.0, "delta": 0.70, "bid": 6.0, "ask": 6.2, "symbol": "C95", "expiry": "2026-07-01"},
        {"side": "call", "strike": 100.0, "delta": 0.50, "bid": 3.0, "ask": 3.2, "symbol": "C100", "expiry": "2026-07-01"},
        {"side": "put", "strike": 100.0, "delta": -0.50, "bid": 2.8, "ask": 3.0, "symbol": "P100", "expiry": "2026-07-01"},
        {"side": "put", "strike": 105.0, "delta": -0.70, "bid": 6.0, "ask": 6.2, "symbol": "P105", "expiry": "2026-07-01"},
    ]
    metrics = compute_strategy_metrics(
        "Long Guts",
        spot=100.0,
        contracts=contracts,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    call = next(leg for leg in metrics["legs"] if leg["side"] == "call")
    put = next(leg for leg in metrics["legs"] if leg["side"] == "put")
    assert call["action"] == "buy" and put["action"] == "buy"
    assert call["strike"] < 100.0 < put["strike"]
