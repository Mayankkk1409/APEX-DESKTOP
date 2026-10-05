"""Explanation text follows the legs, and closed-form payoffs match hand fixtures."""

from __future__ import annotations

from decimal import Decimal

from app.services.strategy_engine import _structure_copy, build_strategy_layer, compute_strategy_metrics
from app.strategies.registry import get_strategy_spec
from app.strategies.structure_math import quote_documented_structure

_MULT = 100
_LONG_CALL_LANGUAGE = (
    "long call",
    "buy a call",
    "buy the recommended contract",
    "unlimited",
)


def _blob(summary: str, execution: str) -> str:
    return f"{summary} {execution}".lower()


def test_bull_put_explanation_does_not_describe_a_long_call() -> None:
    """A put credit spread must not inherit a long-call definition, even if the title does."""
    legs = [
        {"action": "sell", "side": "put", "strike": 100, "mid": 2.50, "expiry": "2026-07-01"},
        {"action": "buy", "side": "put", "strike": 95, "mid": 1.00, "expiry": "2026-07-01"},
    ]
    for title in ("Long Call", "Bull Call Spread", "APEX Benchmark Greeks Strategy", "Bull Put Spread (credit)"):
        summary, execution = _structure_copy(title, legs)
        text = _blob(summary, execution)
        for phrase in _LONG_CALL_LANGUAGE:
            assert phrase not in text, title
        assert "put" in text
        assert "credit" in text
        assert "higher-strike put" in text
        assert "no trade" not in text
        assert "stand aside" not in text


def test_bull_put_layer_copy_matches_the_put_credit_legs() -> None:
    contracts = [
        {"side": "put", "strike": 100.0, "delta": -0.20, "bid": 2.40, "ask": 2.60, "symbol": "P100", "expiry": "2026-07-01"},
        {"side": "put", "strike": 95.0, "delta": -0.10, "bid": 0.90, "ask": 1.10, "symbol": "P95", "expiry": "2026-07-01"},
    ]
    layer = build_strategy_layer(
        strategy_name="Bull Put Spread (credit)",
        composite=78.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "XYZ",
            "spot": 102.0,
            "expiry": "2026-07-01",
            "recommendedContract": {"strike": 100.0, "side": "put", "expiry": "2026-07-01"},
            "contracts": contracts,
        },
        vol_layer={"iv": 0.30, "hv": 0.18, "iv_rank": 60},
        sentiment_layer={"bias": "bullish", "score_0_100": 55},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        ticker="XYZ",
    )
    text = " ".join(
        [
            str(layer["what_is_this"]),
            str(layer["how_to_execute"]),
            str(layer["why_it_fits"]),
        ]
    ).lower()
    for phrase in _LONG_CALL_LANGUAGE:
        assert phrase not in text
    assert "higher-strike put" in text
    metrics = layer["metrics"]
    assert metrics["net_type"] == "credit"
    assert metrics["net_debit_credit"] == 1.5
    assert metrics["max_profit"] == 150.0
    assert metrics["max_loss"] == 350.0
    assert metrics["breakevens"] == [98.5]


def test_vertical_and_single_leg_hand_fixtures() -> None:
    bull_put = [
        {"action": "sell", "side": "put", "strike": "100", "mid": "2.50"},
        {"action": "buy", "side": "put", "strike": "95", "mid": "1.00"},
    ]
    quoted = quote_documented_structure(get_strategy_spec("Bull Put Spread (credit)"), bull_put, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["net_type"] == "credit"
    assert quoted["net_debit_credit"] == Decimal("1.50")
    assert quoted["max_profit"] == Decimal("150.00")
    assert quoted["max_loss"] == Decimal("350.00")
    assert quoted["breakevens"] == [Decimal("98.50")]

    bull_call = [
        {"action": "buy", "side": "call", "strike": "100", "mid": "3.90"},
        {"action": "sell", "side": "call", "strike": "105", "mid": "1.90"},
    ]
    quoted = quote_documented_structure(get_strategy_spec("Bull Call Spread"), bull_call, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["max_loss"] == Decimal("200.00")
    assert quoted["max_profit"] == Decimal("300.00")
    assert quoted["breakevens"] == [Decimal("102.00")]

    bear_put = [
        {"action": "buy", "side": "put", "strike": "100", "mid": "3.00"},
        {"action": "sell", "side": "put", "strike": "95", "mid": "1.20"},
    ]
    quoted = quote_documented_structure(get_strategy_spec("Bear Put Spread"), bear_put, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["net_type"] == "debit"
    assert quoted["net_debit_credit"] == Decimal("1.80")
    assert quoted["max_loss"] == Decimal("180.00")
    assert quoted["max_profit"] == Decimal("320.00")
    assert quoted["breakevens"] == [Decimal("98.20")]

    bear_call = [
        {"action": "sell", "side": "call", "strike": "105", "mid": "2.40"},
        {"action": "buy", "side": "call", "strike": "110", "mid": "0.90"},
    ]
    quoted = quote_documented_structure(get_strategy_spec("Bear Call Spread (credit)"), bear_call, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["net_type"] == "credit"
    assert quoted["net_debit_credit"] == Decimal("1.50")
    assert quoted["max_profit"] == Decimal("150.00")
    assert quoted["max_loss"] == Decimal("350.00")
    assert quoted["breakevens"] == [Decimal("106.50")]

    long_call = [{"action": "buy", "side": "call", "strike": "100", "mid": "4.25"}]
    quoted = quote_documented_structure(get_strategy_spec("Long Call"), long_call, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["max_loss"] == Decimal("425.00")
    assert quoted["max_profit"] is None
    assert quoted["max_profit_unlimited"] is True
    assert quoted["breakevens"] == [Decimal("104.25")]

    long_put = [{"action": "buy", "side": "put", "strike": "100", "mid": "3.40"}]
    quoted = quote_documented_structure(get_strategy_spec("Long Put"), long_put, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["max_loss"] == Decimal("340.00")
    assert quoted["max_profit"] == Decimal("9660.00")
    assert quoted["breakevens"] == [Decimal("96.60")]

    condor = [
        {"action": "sell", "side": "put", "strike": "95", "mid": "1.50"},
        {"action": "buy", "side": "put", "strike": "90", "mid": "0.50"},
        {"action": "sell", "side": "call", "strike": "105", "mid": "1.20"},
        {"action": "buy", "side": "call", "strike": "110", "mid": "0.40"},
    ]
    quoted = quote_documented_structure(get_strategy_spec("Short Iron Condor"), condor, contract_multiplier=_MULT)
    assert quoted is not None
    assert quoted["max_profit"] == Decimal("180.00")
    assert quoted["max_loss"] == Decimal("320.00")
    assert quoted["breakevens"] == [Decimal("93.20"), Decimal("106.80")]


def test_undefined_risk_loss_stays_unlimited() -> None:
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
    summary, execution = _structure_copy("Naked Call", metrics["legs"])
    text = _blob(summary, execution)
    assert "unlimited" in text
    assert "naked short call" in text


def test_calendar_publishes_the_front_expiry_max_profit() -> None:
    front = [
        {"side": "call", "strike": 100.0, "bid": 2.8, "ask": 3.0, "expiry": "2026-08-01", "symbol": "CFRONT"},
    ]
    back = [
        {"side": "call", "strike": 100.0, "bid": 4.8, "ask": 5.0, "expiry": "2026-09-01", "symbol": "CBACK"},
    ]
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=front,
        recommended={"strike": 100.0, "side": "call", "expiry": "2026-08-01"},
        back_month_contracts=back,
        front_expiry="2026-08-01",
        back_expiry="2026-09-01",
        iv=0.28,
        ticker="XYZ",
    )
    assert isinstance(metrics["max_profit"], (int, float))
    assert metrics.get("max_profit_unlimited_allowed") is not True
    note = str(metrics.get("notes") or metrics.get("payoff_notes") or metrics.get("breakeven_assumption_note") or "")
    assert "iv" in note.lower()
    summary, _execution = _structure_copy("Calendar Spread", metrics["legs"])
    assert "back-leg iv" in summary.lower()
    assert "no closed-form max profit" not in summary.lower()
    assert "no trade" not in summary.lower()
