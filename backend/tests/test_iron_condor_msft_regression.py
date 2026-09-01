"""MSFT Short Iron Condor regression — validator must block all three bug classes."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analysis.score_bounds import ScoreOutOfBoundsError, assert_score_in_bounds
from app.analysis.volatility import compute_iv_rank, iv_rank_proxy, range_rank
from app.services.strategy_engine import build_strategy_layer
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT_EXPIRY = (TODAY + timedelta(days=30)).isoformat()
SPOT = 500.0


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(strike * 1000):08d}"


def _leg(
    root: str,
    strike: float,
    side: str,
    *,
    bid: float,
    ask: float,
    action: str | None = None,
) -> dict:
    mid = round((bid + ask) / 2, 2)
    row = {
        "action": action,
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "mid": mid,
        "symbol": _occ(root, FRONT_EXPIRY, side, strike),
        "expiry": FRONT_EXPIRY,
        "delta": 0.2 if side == "call" else -0.2,
        "iv": 0.35,
    }
    return row


def _msft_buggy_metrics() -> dict:
    """Original MSFT iron condor bug: inverted puts + credit/summary mismatch."""
    legs = [
        _leg("MSFT", 492.5, "put", bid=1.66, ask=1.70, action="sell"),
        _leg("MSFT", 490.0, "put", bid=1.71, ask=1.75, action="buy"),
        _leg("MSFT", 505.0, "call", bid=1.92, ask=1.96, action="sell"),
        _leg("MSFT", 510.0, "call", bid=1.74, ask=1.78, action="buy"),
    ]
    return {
        "legs": legs,
        "net_debit_credit": 0.14,
        "net_type": "credit",
        "max_profit": 13.5,
        "max_loss": 236.5,
        "breakevens": [492.37, 505.14],
        "per_contract_multiplier": 100,
    }


def _msft_correct_metrics() -> dict:
    """Corrected MSFT iron condor — monotonic puts, consistent credit math."""
    legs = [
        _leg("MSFT", 492.5, "put", bid=1.76, ask=1.80, action="sell"),
        _leg("MSFT", 490.0, "put", bid=1.61, ask=1.65, action="buy"),
        _leg("MSFT", 505.0, "call", bid=1.92, ask=1.96, action="sell"),
        _leg("MSFT", 510.0, "call", bid=1.74, ask=1.78, action="buy"),
    ]
    credit = round((1.78 + 1.94) - (1.63 + 1.76), 2)
    wing = max(492.5 - 490.0, 510.0 - 505.0)
    return {
        "legs": legs,
        "net_debit_credit": credit,
        "net_type": "credit",
        "max_profit": round(credit * 100, 2),
        "max_loss": round((wing - credit) * 100, 2),
        "breakevens": [round(492.5 - credit, 2), round(505.0 + credit, 2)],
        "per_contract_multiplier": 100,
    }


SPREAD_CONDOR_BUTTERFLY_IDS = [
    sid
    for sid, spec in STRATEGY_REGISTRY.items()
    if spec.payoff_function_ref
    in {
        "payoff_vertical_debit",
        "payoff_vertical_credit",
        "payoff_iron_condor",
        "payoff_long_iron_condor",
        "payoff_butterfly",
        "payoff_short_butterfly",
        "payoff_iron_butterfly",
        "payoff_condor_spread",
    }
    and spec.tradeable
]

TICKERS = ["AAPL", "MSFT", "TSLA"]


def test_msft_buggy_iron_condor_validator_rejects_inverted_puts() -> None:
    result = validate_strategy_output(
        "Short Iron Condor",
        _msft_buggy_metrics(),
        "MSFT",
        scan_scores={"iv_rank": 285.2, "composite": 80, "technical": 73.4},
        spot=SPOT,
    )
    assert not result.valid
    checks = {e.check for e in result.errors}
    assert "moneyness_monotonicity" in checks
    assert "score_bounds" in checks
    assert "credit_recomputation" in checks or "max_profit_credit_match" in checks


def test_msft_corrected_iron_condor_passes_validator() -> None:
    metrics = _msft_correct_metrics()
    result = validate_strategy_output(
        "Short Iron Condor",
        metrics,
        "MSFT",
        scan_scores={"iv_rank": 72.0, "composite": 80, "technical": 73.4},
        spot=SPOT,
    )
    assert result.valid, [(e.check, e.actual) for e in result.errors]


def test_iv_rank_285_hard_fails_at_computation() -> None:
    with pytest.raises(ScoreOutOfBoundsError):
        assert_score_in_bounds("iv_rank", 285.2)


def test_compute_iv_rank_never_exceeds_100() -> None:
    history = [0.15 + i * 0.001 for i in range(30)]
    rank = compute_iv_rank(history, 0.80)["iv_rank"]
    assert rank is not None
    assert 0.0 <= rank <= 100.0


def test_iv_rank_proxy_bounded() -> None:
    """iv/hv ratio that would yield 285 without clamp must hard-fail or cap."""
    proxy = iv_rank_proxy(0.285, 0.04)
    assert proxy is not None
    assert proxy <= 100.0


def test_injected_credit_mismatch_blocked_on_aapl_bull_put() -> None:
    """Same bug class on a different ticker/strategy — credit mismatch."""
    metrics = build_registry_metrics(
        "bull_put_spread_credit",
        spot=100.0,
        contracts=[
            _leg("AAPL", 95.0, "put", bid=1.0, ask=1.2),
            _leg("AAPL", 90.0, "put", bid=0.4, ask=0.6),
            _leg("AAPL", 100.0, "call", bid=2.0, ask=2.2),
        ],
        front_expiry=FRONT_EXPIRY,
        iv=0.30,
        ticker="AAPL",
    )
    assert metrics is not None
    metrics = {**metrics, "net_debit_credit": (metrics["net_debit_credit"] or 0) + 0.05, "max_profit": 999.0}
    result = validate_strategy_output("Bull Put Spread (credit)", metrics, "AAPL")
    assert not result.valid
    assert any(e.check in {"credit_recomputation", "max_profit_credit_match"} for e in result.errors)


def test_build_strategy_layer_blocks_msft_buggy_iv_rank() -> None:
    layer = build_strategy_layer(
        strategy_name="Short Iron Condor",
        composite=82.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={"spot": SPOT, "expiry": FRONT_EXPIRY, "contracts": [], "symbol": "MSFT"},
        vol_layer={"iv_rank": 285.2, "iv": 0.35, "hv": 0.12},
        sentiment_layer={"bias": "neutral", "score_0_100": 55},
        fundamentals_layer={"score": 60},
        tech_score=73.4,
        ticker="MSFT",
    )
    assert layer["tradeable"] is False
    assert layer.get("selection_rationale")


@pytest.mark.parametrize("strategy_id", SPREAD_CONDOR_BUTTERFLY_IDS[:12])
@pytest.mark.parametrize("ticker", TICKERS)
def test_valid_mock_chain_passes_moneyness_and_credit(strategy_id: str, ticker: str) -> None:
    """Parametrize: built metrics from monotonic mock chains must pass validator."""
    strikes = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0]
    contracts: list[dict] = []
    for k in strikes:
        dist = abs(k - 100.0)
        cb = max(0.3, 4.0 - dist * 0.35)
        pb = max(0.3, 3.5 - dist * 0.30)
        contracts.append(_leg(ticker, k, "call", bid=cb, ask=cb + 0.2))
        contracts.append(_leg(ticker, k, "put", bid=pb, ask=pb + 0.2))

    metrics = build_registry_metrics(
        strategy_id,
        spot=100.0,
        contracts=contracts,
        front_expiry=FRONT_EXPIRY,
        iv=0.28,
        ticker=ticker,
    )
    if metrics is None or metrics.get("validation_blocked"):
        pytest.skip(f"{strategy_id} could not build from mock chain")
    spec = STRATEGY_REGISTRY[strategy_id]
    if len(metrics.get("legs") or []) != spec.leg_count:
        pytest.skip(f"{strategy_id} leg count mismatch on mock chain")

    result = validate_strategy_output(
        spec.display_name, metrics, ticker, scan_scores={"iv_rank": 55.0}, spot=100.0
    )
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]


def test_range_rank_caps_outlier_iv() -> None:
    history = [0.20 + i * 0.001 for i in range(25)]
    assert range_rank(history, 0.50) == 100.0
