"""Equity policy, anchor leg consistency, and score bound regression tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analysis.score_bounds import ScoreOutOfBoundsError, assert_score_bounded
from app.analysis.volatility import range_rank
from app.services.strategy_engine import compute_strategy_metrics
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT_EXPIRY = (TODAY + timedelta(days=30)).isoformat()


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(strike * 1000):08d}"


def _leg(strike: float, side: str, *, bid: float, ask: float, delta: float) -> dict:
    mid = (bid + ask) / 2
    return {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "symbol": _occ("NVDA", FRONT_EXPIRY, side, strike),
        "expiry": FRONT_EXPIRY,
        "delta": delta,
        "iv": 0.45,
    }


NVDA_CHAIN = [
    _leg(215.0, "call", bid=8.0, ask=8.4, delta=0.52),
    _leg(220.0, "call", bid=6.2, ask=6.6, delta=0.55),
    _leg(225.0, "call", bid=4.5, ask=4.9, delta=0.48),
    _leg(210.0, "put", bid=5.0, ask=5.4, delta=-0.45),
]


def test_married_call_alias_builds_benchmark_greeks_at_recommended_strike() -> None:
    """Legacy 'Married Call' resolves to APEX Benchmark Greeks — anchor strike == order leg."""
    recommended = {"strike": 215.0, "side": "call", "expiry": FRONT_EXPIRY, "contract_id": _occ("NVDA", FRONT_EXPIRY, "call", 215.0)}
    metrics = compute_strategy_metrics(
        "Married Call",
        spot=218.0,
        contracts=NVDA_CHAIN,
        recommended=recommended,
        front_expiry=FRONT_EXPIRY,
        ticker="NVDA",
    )
    assert len(metrics["legs"]) == 1
    assert metrics["legs"][0]["strike"] == 215.0
    validation = validate_strategy_output(
        "APEX Benchmark Greeks Strategy",
        metrics,
        "NVDA",
        recommended_contract={"strike": 215.0, "side": "call", "expiry": FRONT_EXPIRY},
    )
    assert validation.valid, validation.errors


def test_validator_blocks_deliberate_anchor_strike_mismatch() -> None:
    """Proof: anchor 215 vs order 220 must block before trade card."""
    metrics = compute_strategy_metrics(
        "Bull Call Spread",
        spot=100.0,
        contracts=[
            {
                "side": "call",
                "strike": 100.0,
                "bid": 3.8,
                "ask": 4.0,
                "symbol": _occ("AAPL", FRONT_EXPIRY, "call", 100.0),
                "expiry": FRONT_EXPIRY,
                "delta": 0.55,
            },
            {
                "side": "call",
                "strike": 105.0,
                "bid": 1.8,
                "ask": 2.0,
                "symbol": _occ("AAPL", FRONT_EXPIRY, "call", 105.0),
                "expiry": FRONT_EXPIRY,
                "delta": 0.35,
            },
        ],
        recommended={"strike": 100.0, "side": "call", "expiry": FRONT_EXPIRY},
        front_expiry=FRONT_EXPIRY,
        ticker="AAPL",
    )
    bad_anchor = {"strike": 220.0, "side": "call", "expiry": FRONT_EXPIRY}
    validation = validate_strategy_output("Bull Call Spread", metrics, "AAPL", recommended_contract=bad_anchor)
    assert not validation.valid
    assert any(e.check == "anchor_strike_match" for e in validation.errors)


def test_iv_rank_out_of_history_range_is_capped_not_unbounded() -> None:
    """IV rank must stay in [0,100] even when current IV exceeds historical max."""
    history = [0.20 + i * 0.001 for i in range(25)]
    rank = range_rank(history, 0.50)
    assert rank == 100.0
    assert rank <= 100.0


def test_assert_score_bounded_throws_above_100() -> None:
    """Proof: IV rank > 100 hard-fails."""
    with pytest.raises(ScoreOutOfBoundsError):
        assert_score_bounded("iv_rank", 128.9)


def test_options_only_strategy_rejects_stock_leg_in_payload() -> None:
    metrics = {
        "legs": [
            {
                "action": "buy",
                "side": "stock",
                "strike": 100.0,
                "symbol": "AAPL",
                "mid": 100.0,
            },
            {
                "action": "buy",
                "side": "call",
                "strike": 100.0,
                "expiry": FRONT_EXPIRY,
                "mid": 2.0,
                "symbol": _occ("AAPL", FRONT_EXPIRY, "call", 100.0),
            },
        ],
        "max_profit": None,
        "max_loss": 200.0,
        "breakevens": [102.0],
        "net_debit_credit": 2.0,
        "net_type": "debit",
    }
    validation = validate_strategy_output("Long Call", metrics, "AAPL")
    assert not validation.valid
    assert any(e.check == "equity_forbidden" for e in validation.errors)


def test_leveraged_covered_call_requires_stock_and_call() -> None:
    from app.strategies.metrics_builder import build_registry_metrics

    metrics = build_registry_metrics(
        "leveraged_covered_call",
        spot=100.0,
        contracts=NVDA_CHAIN,
        front_expiry=FRONT_EXPIRY,
        iv=0.35,
        ticker="NVDA",
        recommended={"strike": 220.0, "side": "call", "expiry": FRONT_EXPIRY},
    )
    assert metrics is not None
    assert len(metrics["legs"]) == 2
    assert any(l.get("side") == "stock" for l in metrics["legs"])
    assert metrics["max_loss"] is not None
    assert metrics["max_loss"] > 100 * 100  # stock + call combined, not call-only
