"""Section 10 gate, payoff, and order-guard fixtures."""

from __future__ import annotations

import math

import pytest

from app.analysis.gate_config import hysteresis_action, refuse_if_checks_failed
from app.services.fills import execute_strategy_legs
from app.services.strategy_engine import build_strategy_layer, select_strategy
from app.strategies.payoffs.core import apex_strategy_payoff

AAPL = "AAPL261030C00330000"
PLAIN_LONG = {"Long Call", "Long Put", "APEX Benchmark Greeks Strategy"}


def _aapl_contract(**overrides: object) -> dict:
    row = {
        "symbol": AAPL,
        "side": "call",
        "strike": 330.0,
        "expiry": "2026-10-30",
        "delta": 0.58,
        "theta": -0.18,
        "iv": 0.2705,
        "bid": 11.70,
        "ask": 12.22,
        "multiplier": 100,
    }
    row.update(overrides)
    return row


def _aapl_layer(contract: dict, **kwargs: object) -> dict:
    base = dict(
        strategy_name="APEX Benchmark Greeks Strategy",
        composite=63.1,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 328.0,
            "expiry": "2026-10-30",
            "recommendedContract": {"strike": 330.0, "side": "call", "expiry": "2026-10-30", "symbol": AAPL, "iv": 0.2705},
            "contracts": [contract],
        },
        vol_layer={"iv": 0.2705, "atm_iv": 0.2705, "hv": 0.2246, "iv_rank": 46.05037606326132},
        sentiment_layer={"bias": "bullish", "score_0_100": 62},
        fundamentals_layer={"score": 60},
        tech_score=74.0,
        ticker="AAPL",
        auto_exec_threshold=40.0,
    )
    base.update(kwargs)
    return build_strategy_layer(**base)  # type: ignore[arg-type]


def test_aapl_long_call_is_not_executable_when_iv_is_not_below_hv() -> None:
    layer = _aapl_layer(_aapl_contract())
    metrics = layer["metrics"]
    assert metrics["breakevens"][0] == pytest.approx(341.96, abs=0.02)
    assert metrics["max_loss"] == pytest.approx(1196, abs=0.5)
    assert layer["execution_banner"] == "NOT EXECUTABLE"
    assert layer["auto_exec_blocked"] is True
    assert layer["clears_threshold"] is False
    assert "meets your auto-execution threshold" not in layer["why_it_fits"]
    assert "contract IV is not below HV" in " ".join(layer["risk_notes"])
    assert "46.1" in layer["why_it_fits"]
    assert "46.05037606326132" not in layer["why_it_fits"]
    assert layer["vol_regime"] == "fair"
    assert layer["vol_regime"] != "sell premium"


def test_aapl_fails_absolute_theta_mode() -> None:
    from app.analysis import gate_config

    original = gate_config.theta_filter_mode
    gate_config.theta_filter_mode = lambda: "abs_per_share"  # type: ignore[method-assign]
    try:
        layer = _aapl_layer(_aapl_contract())
    finally:
        gate_config.theta_filter_mode = original  # type: ignore[method-assign]
    joined = " ".join(layer["risk_notes"])
    assert "daily theta" in joined
    assert "0.05" in joined
    assert "delta/theta" in joined
    assert layer["execution_banner"] == "NOT EXECUTABLE"


def _spread(mid: float, pct: float) -> tuple[float, float]:
    width = mid * pct
    return round(mid - width / 2, 4), round(mid + width / 2, 4)


def test_nflx_diagonal_loss_is_positive_and_not_sell_premium() -> None:
    long_bid, long_ask = _spread(4.14, 0.157)
    short_bid, short_ask = _spread(2.07, 0.157)
    long_leg = {
        "symbol": "NFLX261023P00069000",
        "side": "put",
        "strike": 69.0,
        "expiry": "2026-10-23",
        "bid": long_bid,
        "ask": long_ask,
        "iv": 0.73,
        "delta": -0.48,
    }
    short_leg = {
        "symbol": "NFLX261016P00068000",
        "side": "put",
        "strike": 68.0,
        "expiry": "2026-10-16",
        "bid": short_bid,
        "ask": short_ask,
        "iv": 0.59,
        "delta": -0.42,
    }
    layer = build_strategy_layer(
        strategy_name="Diagonal Spread (bearish)",
        composite=60.0,
        direction="bearish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "NFLX",
            "spot": 70.0,
            "expiry": "2026-10-16",
            "recommendedContract": {"strike": 68.0, "side": "put", "expiry": "2026-10-16"},
            "contracts": [short_leg],
        },
        vol_layer={"iv": 0.22, "atm_iv": 0.22, "hv": 0.28, "iv_rank": 6.16},
        sentiment_layer={"bias": "bearish", "score_0_100": 48},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="NFLX",
        back_month_contracts=[long_leg],
        back_expiry="2026-10-23",
    )
    metrics = layer["metrics"]
    assert metrics["max_loss"] == pytest.approx(207, abs=1.0)
    assert metrics["max_loss"] > 0
    assert "-207" not in str(metrics["max_loss"])
    assert metrics["breakevens"]
    assert metrics["max_profit"] not in (None, "—")
    assert layer["vol_regime"] != "sell premium"
    assert layer["execution_banner"] == "NOT EXECUTABLE"
    assert layer["auto_exec_blocked"] is True
    joined = " ".join(layer["risk_notes"])
    assert "Stale or suspect quote" in joined or "not below 10%" in joined
    assert metrics.get("breakeven_assumption_note") or metrics.get("payoff_notes")


def test_msft_high_iv_rank_is_not_a_plain_long_call() -> None:
    label = select_strategy(
        composite=80.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.35,
        hv=0.217,
        ivr=100.0,
        tech_score=85.0,
        sentiment_score=70.0,
        confirmed_pattern_count=1,
    )
    assert label not in PLAIN_LONG
    bid, ask = _spread(29.75, 0.085)
    delta = 0.37 * 1.79
    layer = build_strategy_layer(
        strategy_name="Long Call",
        composite=80.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "MSFT",
            "spot": 510.0,
            "expiry": "2026-10-30",
            "recommendedContract": {"strike": 500.0, "side": "call", "expiry": "2026-10-30", "iv": 0.35},
            "contracts": [
                {
                    "symbol": "MSFT261030C00500000",
                    "side": "call",
                    "strike": 500.0,
                    "expiry": "2026-10-30",
                    "bid": bid,
                    "ask": ask,
                    "delta": delta,
                    "theta": -0.37,
                    "iv": 0.35,
                }
            ],
        },
        vol_layer={"iv": 0.3522, "atm_iv": 0.3367, "hv": 0.217, "iv_rank": 100},
        sentiment_layer={"bias": "bullish", "score_0_100": 70},
        fundamentals_layer={"score": 60},
        tech_score=85.0,
        ticker="MSFT",
        auto_exec_threshold=40.0,
    )
    assert layer["execution_banner"] == "NOT EXECUTABLE"
    assert layer["auto_exec_blocked"] is True
    assert layer["clears_threshold"] is False
    assert "meets your auto-execution threshold" not in layer["why_it_fits"]
    assert "Failed checks" in layer["why_it_fits"]
    text = layer["why_it_fits"]
    assert text.count("33.67%") <= 1
    assert text.count("35.22%") <= 1


def test_hysteresis_blocks_entry_and_keeps_an_open_position() -> None:
    assert hysteresis_action(42, in_position=False, entry_min=45, exit_min=40) == "no_entry"
    assert hysteresis_action(42, in_position=True, entry_min=45, exit_min=40) == "hold"
    contracts = [
        {
            "side": "call",
            "strike": 100.0,
            "delta": 0.55,
            "bid": 3.00,
            "ask": 3.10,
            "symbol": "XYZ261120C00100000",
            "expiry": "2026-11-20",
        },
        {
            "side": "call",
            "strike": 105.0,
            "delta": 0.35,
            "bid": 1.40,
            "ask": 1.48,
            "symbol": "XYZ261120C00105000",
            "expiry": "2026-11-20",
        },
    ]
    common = dict(
        strategy_name="Bull Call Spread",
        composite=42.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={
            "symbol": "XYZ",
            "spot": 100.0,
            "expiry": "2026-11-20",
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-11-20"},
            "contracts": contracts,
        },
        vol_layer={"iv": 0.20, "hv": 0.30, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        ticker="XYZ",
        auto_exec_threshold=30.0,
    )
    fresh = build_strategy_layer(**common)
    assert fresh["position_action"] == "no_entry"
    assert fresh["clears_threshold"] is False
    assert "meets your auto-execution threshold" not in fresh["why_it_fits"]
    held = build_strategy_layer(**common, in_position=True)
    assert held["position_action"] == "hold"
    assert held["clears_threshold"] is False
    assert "meets your auto-execution threshold" not in held["why_it_fits"]


def test_apex_double_calendar_profit_peaks_near_a_strike_and_is_finite() -> None:
    result = apex_strategy_payoff(
        spot=100.0,
        call_strike=105.0,
        put_strike=95.0,
        net_debit=2.2,
        front_dte_days=7,
        back_dte_days=21,
        iv=0.40,
        contract_multiplier=100,
    )
    assert result["max_profit_unlimited_allowed"] is False
    assert isinstance(result["max_profit"], float)
    assert math.isfinite(result["max_profit"])
    assert result["max_loss"] > 0
    grid = result["payoff_grid"]
    assert len(grid) >= 20
    best = max(grid, key=lambda row: row["pnl"])
    gap = 100.0 * (1 + 3 * 0.40 * math.sqrt(7 / 365))
    at_gap = min(grid, key=lambda row: abs(row["underlying"] - gap))
    near_strike = min(abs(best["underlying"] - 105.0), abs(best["underlying"] - 95.0))
    assert near_strike < abs(best["underlying"] - gap)
    assert best["pnl"] > at_gap["pnl"]
    assert "unlimited" not in result["payoff_notes"].lower()


def test_order_guard_rejects_a_failed_check_even_if_auto_execute_is_forced() -> None:
    with pytest.raises(ValueError, match="pre-trade checks did not all pass"):
        refuse_if_checks_failed(checks_passed=False, auto_execute=True)


@pytest.mark.asyncio
async def test_execute_strategy_legs_refuses_before_submission() -> None:
    with pytest.raises(ValueError, match="pre-trade checks did not all pass"):
        await execute_strategy_legs(
            user=None,  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=None,
            legs=[{"symbol": "AAPL", "side": "buy", "qty": 1}],
            checks_passed=False,
            auto_execute=True,
        )
