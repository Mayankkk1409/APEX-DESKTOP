"""Synthetic structures use the registry geometry, not a vertical or a straddle."""

from __future__ import annotations

from app.services.strategy_engine import _structure_copy
from app.strategies.metrics_builder import build_registry_metrics

EXPIRY = "2026-11-20"
SPOT = 100.0


def _quote(strike: float, side: str, *, bid: float, ask: float, expiry: str = EXPIRY) -> dict:
    mid = (bid + ask) / 2
    cp = "C" if side == "call" else "P"
    return {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "expiry": expiry,
        "symbol": f"AAPL261120{cp}{int(strike * 1000):08d}",
        "delta": 0.5 if side == "call" else -0.5,
    }


def _split_chain() -> list[dict]:
    """Nearest call is 90 and nearest put is 105. Both sides exist at 105."""
    return [
        _quote(90, "call", bid=12.0, ask=12.4),
        _quote(110, "call", bid=1.0, ask=1.2),
        _quote(105, "call", bid=2.0, ask=2.4),
        _quote(105, "put", bid=6.0, ask=6.4),
        _quote(115, "put", bid=14.0, ask=14.4),
        _quote(90, "put", bid=1.0, ask=1.2),
    ]


def _build(strategy_id: str, contracts: list[dict] | None = None) -> dict:
    metrics = build_registry_metrics(
        strategy_id,
        spot=SPOT,
        contracts=contracts if contracts is not None else _split_chain(),
        front_expiry=EXPIRY,
        iv=0.25,
        ticker="AAPL",
    )
    assert metrics is not None
    return metrics


def _pairs(legs: list[dict]) -> list[tuple]:
    return [(leg["action"], leg["side"], leg.get("quantity") or 1) for leg in legs]


def test_synthetic_long_stock_is_same_strike_call_and_put() -> None:
    metrics = _build("synthetic_long_stock")
    legs = metrics["legs"]
    assert _pairs(legs) == [("buy", "call", 1), ("sell", "put", 1)]
    assert {leg["strike"] for leg in legs} == {105.0}
    assert {leg["expiry"] for leg in legs} == {EXPIRY}
    assert metrics.get("validation_blocked") is not True


def test_synthetic_short_stock_is_same_strike_call_and_put() -> None:
    metrics = _build("synthetic_short_stock")
    legs = metrics["legs"]
    assert _pairs(legs) == [("sell", "call", 1), ("buy", "put", 1)]
    assert {leg["strike"] for leg in legs} == {105.0}
    assert {leg["expiry"] for leg in legs} == {EXPIRY}


def test_synthetic_stock_blocks_when_call_and_put_do_not_share_a_strike() -> None:
    contracts = [
        _quote(90, "call", bid=12.0, ask=12.4),
        _quote(105, "put", bid=6.0, ask=6.4),
    ]
    for strategy_id in ("synthetic_long_stock", "synthetic_short_stock"):
        metrics = _build(strategy_id, contracts)
        assert metrics.get("validation_blocked") is True
        assert metrics["legs"] == []


def test_synthetic_call_is_long_stock_plus_long_put() -> None:
    metrics = _build("synthetic_call")
    legs = metrics["legs"]
    assert _pairs(legs) == [("buy", "stock", 100), ("buy", "put", 1)]
    assert legs[1]["expiry"] == EXPIRY
    assert all(leg["side"] != "call" for leg in legs)
    assert metrics.get("max_profit_unlimited_allowed") is True
    assert metrics["max_profit"] is None
    assert metrics["max_loss"] is not None
    summary, _execution = _structure_copy("Synthetic Call", legs)
    assert "long stock plus a long put" in summary.lower()


def test_synthetic_put_is_short_stock_plus_long_call() -> None:
    metrics = _build("synthetic_put")
    legs = metrics["legs"]
    assert _pairs(legs) == [("sell", "stock", 100), ("buy", "call", 1)]
    assert legs[1]["expiry"] == EXPIRY
    assert all(leg["side"] != "put" for leg in legs)
    assert metrics.get("max_profit_unlimited_allowed") is not True
    assert metrics["max_profit"] is not None
    assert metrics["max_loss"] is not None
    summary, _execution = _structure_copy("Synthetic Put", legs)
    assert "short stock plus a long call" in summary.lower()


def test_synthetic_straddle_is_long_stock_plus_two_puts() -> None:
    metrics = _build("synthetic_straddle")
    legs = metrics["legs"]
    assert _pairs(legs) == [("buy", "stock", 100), ("buy", "put", 2)]
    assert legs[1]["expiry"] == EXPIRY
    assert all(leg["side"] != "call" for leg in legs)
    assert metrics.get("max_profit_unlimited_allowed") is True
    assert metrics["max_profit"] is None
    assert metrics["max_loss"] is not None
    summary, _execution = _structure_copy("Synthetic Straddle", legs)
    assert "two long puts" in summary.lower()
