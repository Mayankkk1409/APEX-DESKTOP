"""Strategy registry validation, calendar spread, APEX Strategy, and safeguard regression tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.analysis.layers import APEX_STRATEGY_NAME
from app.services.apex_strategy import ApexStrategyInput, check_apex_strategy_eligibility
from app.services.strategy_engine import compute_strategy_metrics, build_strategy_layer
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.knowledge_base import (
    GAMMA_CLASSIFIER,
    GAMMA_SUMMARY,
    REQUIRED_KB_FIELDS,
    entry_for,
    knowledge_entries,
    validate_entries,
    validate_knowledge_base,
)
from app.strategies.registry import STRATEGY_REGISTRY, get_strategy_spec, implemented_strategy_names
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT_EXPIRY = (TODAY + timedelta(days=30)).isoformat()
BACK_EXPIRY = (TODAY + timedelta(days=60)).isoformat()


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(strike * 1000):08d}"


def _leg(strike: float, side: str, expiry: str, *, bid: float, ask: float, root: str = "AAPL") -> dict:
    mid = (bid + ask) / 2
    return {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "symbol": _occ(root, expiry, side, strike),
        "expiry": expiry,
        "delta": 0.5 if side == "call" else -0.5,
        "iv": 0.25,
    }


FRONT_CHAIN = [
    _leg(100.0, "call", FRONT_EXPIRY, bid=2.0, ask=2.2),
    _leg(100.0, "put", FRONT_EXPIRY, bid=1.8, ask=2.0),
    _leg(105.0, "call", FRONT_EXPIRY, bid=0.8, ask=1.0),
    _leg(95.0, "put", FRONT_EXPIRY, bid=0.7, ask=0.9),
]

BACK_CHAIN = [
    _leg(100.0, "call", BACK_EXPIRY, bid=3.5, ask=3.7),
    _leg(100.0, "put", BACK_EXPIRY, bid=3.2, ask=3.4),
    _leg(105.0, "call", BACK_EXPIRY, bid=2.0, ask=2.2),
    _leg(95.0, "put", BACK_EXPIRY, bid=1.5, ask=1.7),
]

BULL_CALL_CHAIN = [
    _leg(100.0, "call", FRONT_EXPIRY, bid=3.8, ask=4.0),
    _leg(105.0, "call", FRONT_EXPIRY, bid=1.8, ask=2.0),
    _leg(100.0, "put", FRONT_EXPIRY, bid=1.9, ask=2.1),
]


def test_registry_has_100_strategies() -> None:
    assert len(STRATEGY_REGISTRY) == 100


def test_calendar_spread_two_legs_same_strike_different_expiry() -> None:
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=FRONT_CHAIN,
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=BACK_CHAIN,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    assert len(metrics["legs"]) == 2
    actions = {leg["action"] for leg in metrics["legs"]}
    assert actions == {"buy", "sell"}
    sell_leg = next(l for l in metrics["legs"] if l["action"] == "sell")
    buy_leg = next(l for l in metrics["legs"] if l["action"] == "buy")
    assert sell_leg["expiry"] == FRONT_EXPIRY
    assert buy_leg["expiry"] == BACK_EXPIRY
    assert sell_leg["strike"] == buy_leg["strike"] == 100.0
    assert sell_leg["symbol"] != buy_leg["symbol"]
    validation = validate_strategy_output("Calendar Spread", metrics, "AAPL")
    assert validation.valid, validation.errors


def test_calendar_max_profit_is_finite_not_unlimited() -> None:
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=FRONT_CHAIN,
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=BACK_CHAIN,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    assert isinstance(metrics["max_profit"], (int, float))
    assert metrics["max_profit"] != "Unlimited"
    assert metrics["max_profit_unlimited_allowed"] is False
    assert metrics.get("max_profit_iv_assumption_dependent") is True


def test_calendar_breakeven_is_range_not_k_minus_premium() -> None:
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=FRONT_CHAIN,
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=BACK_CHAIN,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    bes = metrics["breakevens"]
    assert len(bes) >= 2
    naive_be = 100.0 - (metrics["net_debit_credit"] or 0)
    assert not any(abs(b - naive_be) < 0.01 for b in bes)


def test_validator_blocks_deliberate_missing_calendar_leg() -> None:
    """Regression: single-leg calendar must be blocked by validator."""
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=FRONT_CHAIN,
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=[],  # missing back month → only 0-1 legs
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    validation = validate_strategy_output("Calendar Spread", metrics, "AAPL")
    assert not validation.valid
    assert any(e.check == "leg_count" for e in validation.errors)


def test_validator_blocks_deliberate_missing_leg_injection() -> None:
    """Proof test: manually inject single-leg calendar payload — validator must block."""
    bad_metrics = {
        "legs": [
            {
                "action": "buy",
                "side": "call",
                "strike": 100.0,
                "expiry": BACK_EXPIRY,
                "mid": 3.6,
                "symbol": _occ("AAPL", BACK_EXPIRY, "call", 100.0),
            }
        ],
        "max_profit": None,
        "max_loss": 360.0,
        "breakevens": [317.12],
        "net_debit_credit": 3.6,
        "net_type": "debit",
    }
    validation = validate_strategy_output("Calendar Spread", bad_metrics, "AAPL")
    assert not validation.valid
    checks = {e.check for e in validation.errors}
    assert "leg_count" in checks


@pytest.mark.parametrize("ticker", ["AAPL", "TSLA"])
def test_bull_call_spread_validates_for_tickers(ticker: str) -> None:
    root = ticker
    chain = [
        _leg(100.0, "call", FRONT_EXPIRY, bid=3.8, ask=4.0, root=root),
        _leg(105.0, "call", FRONT_EXPIRY, bid=1.8, ask=2.0, root=root),
    ]
    metrics = compute_strategy_metrics(
        "Bull Call Spread",
        spot=100.0,
        contracts=chain,
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        front_expiry=FRONT_EXPIRY,
        ticker=ticker,
    )
    validation = validate_strategy_output("Bull Call Spread", metrics, ticker, spot=100.0)
    assert validation.valid, validation.errors
    assert metrics["max_profit"] is not None
    assert len(metrics["breakevens"]) == 1


def test_build_strategy_layer_blocks_invalid_calendar() -> None:
    layer = build_strategy_layer(
        strategy_name="Calendar Spread",
        composite=80.0,
        direction="neutral",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 100.0,
            "expiry": FRONT_EXPIRY,
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
            "contracts": FRONT_CHAIN,
        },
        vol_layer={"iv_rank": 50, "iv": 0.25},
        sentiment_layer={"bias": "neutral", "score_0_100": 55},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        back_month_contracts=None,
        back_expiry=None,
        ticker="AAPL",
    )
    assert layer["tradeable"] is False
    assert layer["validation_errors"]


def test_double_calendar_is_implemented() -> None:
    spec = get_strategy_spec("double_calendar")
    assert spec is not None
    assert spec.payoff_function_ref == "payoff_double_calendar"
    metrics = build_registry_metrics(
        "double_calendar",
        spot=100.0,
        contracts=FRONT_CHAIN,
        back_month_contracts=BACK_CHAIN,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    assert metrics is not None
    validation = validate_strategy_output("Double Calendar", metrics, "AAPL")
    assert validation.valid, validation.errors


def test_audit_implemented_vs_registry() -> None:
    implemented = implemented_strategy_names()
    assert "Calendar Spread" in implemented
    assert "Bull Call Spread" in implemented
    assert APEX_STRATEGY_NAME in implemented


def _apex_front_back_chains() -> tuple[list[dict], list[dict]]:
    """OTM call/put at 105/95 with matching back-month legs for APEX Strategy."""
    front = [
        _leg(105.0, "call", FRONT_EXPIRY, bid=1.2, ask=1.4, root="AAPL"),
        _leg(95.0, "put", FRONT_EXPIRY, bid=1.0, ask=1.2, root="AAPL"),
        _leg(100.0, "call", FRONT_EXPIRY, bid=2.5, ask=2.7, root="AAPL"),
        _leg(100.0, "put", FRONT_EXPIRY, bid=2.3, ask=2.5, root="AAPL"),
    ]
    for row in front:
        if row["side"] == "call" and row["strike"] == 105.0:
            row["delta"] = 0.20
        if row["side"] == "put" and row["strike"] == 95.0:
            row["delta"] = -0.20
    back = [
        _leg(105.0, "call", BACK_EXPIRY, bid=2.4, ask=2.6, root="AAPL"),
        _leg(95.0, "put", BACK_EXPIRY, bid=2.0, ask=2.2, root="AAPL"),
    ]
    return front, back


def test_apex_strategy_four_legs_when_eligible() -> None:
    front, back = _apex_front_back_chains()
    metrics = compute_strategy_metrics(
        APEX_STRATEGY_NAME,
        spot=100.0,
        contracts=front,
        recommended={"strike": 105.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=back,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.40,
        ticker="AAPL",
    )
    assert len(metrics["legs"]) == 4
    actions = {(l["action"], l["side"]) for l in metrics["legs"]}
    assert ("sell", "call") in actions
    assert ("sell", "put") in actions
    assert ("buy", "call") in actions
    assert ("buy", "put") in actions
    sell_expiries = {l["expiry"] for l in metrics["legs"] if l["action"] == "sell"}
    buy_expiries = {l["expiry"] for l in metrics["legs"] if l["action"] == "buy"}
    assert sell_expiries == {FRONT_EXPIRY}
    assert buy_expiries == {BACK_EXPIRY}
    validation = validate_strategy_output(APEX_STRATEGY_NAME, metrics, "AAPL")
    assert validation.valid, validation.errors
    assert metrics.get("max_profit_unlimited_allowed") is not True
    assert isinstance(metrics.get("max_profit"), (int, float))
    assert len(metrics["breakevens"]) >= 2


def test_apex_strategy_blocked_without_back_month() -> None:
    front, _ = _apex_front_back_chains()
    metrics = compute_strategy_metrics(
        APEX_STRATEGY_NAME,
        spot=100.0,
        contracts=front,
        recommended={"strike": 105.0, "side": "call", "expiry": FRONT_EXPIRY},
        back_month_contracts=None,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY,
        iv=0.40,
        ticker="AAPL",
    )
    validation = validate_strategy_output(APEX_STRATEGY_NAME, metrics, "AAPL")
    assert not validation.valid
    layer = build_strategy_layer(
        strategy_name=APEX_STRATEGY_NAME,
        composite=85.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 100.0,
            "expiry": FRONT_EXPIRY,
            "recommendedContract": {"strike": 105.0, "side": "call", "expiry": FRONT_EXPIRY},
            "contracts": front,
        },
        vol_layer={"iv_rank": 75, "iv": 0.40},
        sentiment_layer={},
        fundamentals_layer={"score": 60},
        tech_score=78.0,
        ticker="AAPL",
    )
    assert layer["tradeable"] is False
    assert layer["validation_errors"]


def test_apex_strategy_eligibility_blocked_when_gates_fail() -> None:
    result = check_apex_strategy_eligibility(
        ApexStrategyInput(
            catalyst_days=3,
            term_structure_inverted=False,
            front_ivr=60.0,
            four_leg_structure=False,
            legs_same_strikes=False,
        )
    )
    assert result.eligible is False
    assert len(result.rejection_reasons) >= 2


def test_build_strategy_layer_never_tradeable_with_validation_errors() -> None:
    front, _ = _apex_front_back_chains()
    layer = build_strategy_layer(
        strategy_name=APEX_STRATEGY_NAME,
        composite=88.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 100.0,
            "expiry": FRONT_EXPIRY,
            "contracts": front,
        },
        vol_layer={"iv_rank": 75, "iv": 0.40},
        sentiment_layer={},
        fundamentals_layer={"score": 60},
        tech_score=80.0,
        ticker="AAPL",
    )
    assert layer["tradeable"] is False
    assert layer["validation_errors"]
    assert layer["selected_strategy"] == APEX_STRATEGY_NAME
    assert any("Pre-trade check" in note for note in layer["risk_notes"])


def test_wrong_leg_count_blocks_trade_card() -> None:
    bad_metrics = {
        "legs": [
            {
                "action": "buy",
                "side": "call",
                "strike": 100.0,
                "expiry": BACK_EXPIRY,
                "mid": 3.6,
                "symbol": _occ("AAPL", BACK_EXPIRY, "call", 100.0),
            },
            {
                "action": "buy",
                "side": "put",
                "strike": 95.0,
                "expiry": BACK_EXPIRY,
                "mid": 2.1,
                "symbol": _occ("AAPL", BACK_EXPIRY, "put", 95.0),
            },
        ],
        "max_profit": None,
        "max_loss": 100.0,
        "breakevens": [90.0, 110.0],
        "net_debit_credit": 5.7,
        "net_type": "debit",
    }
    validation = validate_strategy_output(APEX_STRATEGY_NAME, bad_metrics, "AAPL")
    assert not validation.valid
    assert any(e.check == "leg_count" for e in validation.errors)
    layer = build_strategy_layer(
        strategy_name=APEX_STRATEGY_NAME,
        composite=90.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={"symbol": "AAPL", "spot": 100.0, "contracts": FRONT_CHAIN},
        vol_layer={"iv": 0.35},
        sentiment_layer={},
        fundamentals_layer={},
        tech_score=80.0,
        ticker="AAPL",
    )
    if layer["validation_errors"]:
        assert layer["tradeable"] is False


try:
    from hypothesis import given, settings
    import hypothesis.strategies as st

    @given(
        strike=st.floats(min_value=50.0, max_value=200.0),
        net_debit=st.floats(min_value=0.05, max_value=5.0),
        iv=st.floats(min_value=0.1, max_value=0.8),
    )
    @settings(max_examples=40, deadline=None)
    def test_calendar_payoff_invariants_fuzz(strike: float, net_debit: float, iv: float) -> None:
        from app.strategies.payoffs import calendar_spread_payoff

        payoff = calendar_spread_payoff(
            spot=strike,
            strike=round(strike, 2),
            net_debit=net_debit,
            front_dte_days=30,
            back_dte_days=60,
            iv=iv,
            side="call",
        )
        assert isinstance(payoff["max_profit"], (int, float))
        assert isinstance(payoff["max_loss"], (int, float))
        assert payoff["max_profit"] != "Unlimited"
        if payoff["breakevens"]:
            assert payoff["breakevens"][0] <= payoff["breakevens"][-1]

except ImportError:
    pass


def test_knowledge_base_startup_validator_is_clean() -> None:
    assert validate_knowledge_base() == []


def test_validator_fails_when_a_required_field_is_removed() -> None:
    """CI uses the same validator as API startup. A blank required field must fail."""
    entries = knowledge_entries()
    sample_id = "long_call"
    for field in REQUIRED_KB_FIELDS:
        broken = replace(entries[sample_id], **{field: ""})
        snapshot = dict(entries)
        snapshot[sample_id] = broken
        errors = validate_entries(snapshot)
        assert any(sample_id in err and field in err for err in errors), field


def test_gamma_trampoline_label_stays_off_the_double_calendar() -> None:
    gamma = entry_for("Gamma Trampoline™")
    calendar = entry_for("double_calendar")
    apex = entry_for("APEX Strategy")
    assert gamma is not None and calendar is not None and apex is not None
    assert gamma.title == "Gamma Trampoline™"
    assert GAMMA_SUMMARY in gamma.summary
    assert GAMMA_CLASSIFIER in gamma.when_not_to_use
    assert gamma.dte_window == "5 to 10 calendar days before earnings"
    assert gamma.dte_min == 5 and gamma.dte_max == 10
    assert gamma.vega_sign == "long" and gamma.theta_sign == "positive" and gamma.gamma_sign == "short"
    assert calendar.title == "Double Calendar"
    assert "Gamma Trampoline" not in calendar.title
    assert calendar.dte_min is None and calendar.dte_max is None
    assert apex.title == "APEX Strategy"
    assert GAMMA_CLASSIFIER in apex.when_not_to_use
    assert apex.dte_min is None and apex.dte_max is None
    buy = entry_for("apex_benchmark_greeks_buy")
    sell = entry_for("apex_benchmark_greeks_sell")
    assert buy is not None and sell is not None
    assert (buy.dte_min, buy.dte_max) == (30, 90)
    assert (sell.dte_min, sell.dte_max) == (30, 45)
    assert (buy.vega_sign, buy.theta_sign, buy.gamma_sign) == ("long", "negative", "long")
    assert (sell.vega_sign, sell.theta_sign, sell.gamma_sign) == ("short", "positive", "short")
    married = entry_for("married_put")
    assert married is not None and (married.dte_min, married.dte_max) == (30, 45)
