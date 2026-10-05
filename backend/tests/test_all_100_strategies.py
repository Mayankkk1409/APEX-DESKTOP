"""Parametrized validation for all 100 APEX encyclopedia strategies."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT_EXPIRY = (TODAY + timedelta(days=30)).isoformat()
BACK_EXPIRY = (TODAY + timedelta(days=60)).isoformat()
ROOT = "AAPL"
SPOT = 100.0


def _occ(expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{ROOT}{yymmdd}{cp}{int(strike * 1000):08d}"


def _leg(strike: float, side: str, expiry: str, *, bid: float, ask: float, delta: float | None = None) -> dict:
    mid = (bid + ask) / 2
    row = {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "symbol": _occ(expiry, side, strike),
        "expiry": expiry,
        "delta": delta if delta is not None else (0.5 if side == "call" else -0.5),
        "iv": 0.25,
    }
    return row


def _rich_chain(expiry: str) -> list[dict]:
    """Multi-strike chain for spreads, butterflies, condors."""
    strikes = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0]
    rows: list[dict] = []
    for k in strikes:
        dist = abs(k - SPOT)
        cb = max(0.3, 4.0 - dist * 0.35)
        pb = max(0.3, 3.5 - dist * 0.30)
        cd = 0.55 - (k - SPOT) * 0.04
        pd = -0.45 + (k - SPOT) * 0.04
        rows.append(_leg(k, "call", expiry, bid=cb, ask=cb + 0.2, delta=cd))
        rows.append(_leg(k, "put", expiry, bid=pb, ask=pb + 0.2, delta=pd))
    return rows


FRONT = _rich_chain(FRONT_EXPIRY)
BACK = _rich_chain(BACK_EXPIRY)

BACK_MONTH_STRATEGIES = {
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

NO_LEG_STRATEGIES = {
    "no_trade_insufficient_conviction",
    "no_trade_wait_iv_crush",
}


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_REGISTRY.keys()))
def test_strategy_builds_and_validates(strategy_id: str) -> None:
    spec = STRATEGY_REGISTRY[strategy_id]
    if strategy_id in NO_LEG_STRATEGIES:
        result = validate_strategy_output(spec.display_name, {"legs": [], "max_profit": None, "max_loss": None, "breakevens": []}, ROOT)
        assert result.valid, [e.check for e in result.errors]
        return

    back = BACK if strategy_id in BACK_MONTH_STRATEGIES else None
    back_exp = BACK_EXPIRY if strategy_id in BACK_MONTH_STRATEGIES else None

    metrics = build_registry_metrics(
        strategy_id,
        spot=SPOT,
        contracts=FRONT,
        back_month_contracts=back,
        front_expiry=FRONT_EXPIRY,
        back_expiry=back_exp,
        iv=0.25,
        ticker=ROOT,
        recommended={"strike": SPOT, "side": "call", "expiry": FRONT_EXPIRY},
    )
    assert metrics is not None, f"No metrics for {strategy_id}"
    assert spec.payoff_function_ref is not None, f"Missing payoff ref for {strategy_id}"

    if metrics.get("validation_blocked"):
        pytest.skip(f"{strategy_id} blocked without optional chain data")

    assert len(metrics.get("legs") or []) == spec.leg_count, (
        f"{strategy_id}: expected {spec.leg_count} legs, got {len(metrics.get('legs') or [])}"
    )

    validation = validate_strategy_output(spec.display_name, metrics, ROOT, spot=SPOT)
    assert validation.valid, [(e.check, e.expected, e.actual) for e in validation.errors]


def test_all_implemented_have_payoff_ref() -> None:
    missing = [sid for sid, s in STRATEGY_REGISTRY.items() if sid not in NO_LEG_STRATEGIES and s.payoff_function_ref is None]
    assert missing == [], f"Strategies missing payoff_function_ref: {missing}"


def test_implemented_count() -> None:
    implemented = sum(1 for s in STRATEGY_REGISTRY.values() if s.payoff_function_ref is not None)
    assert implemented == 98  # 100 minus 2 NO TRADE advisory entries


try:
    from hypothesis import given, settings
    import hypothesis.strategies as st

    @given(st.sampled_from([sid for sid in STRATEGY_REGISTRY if sid not in NO_LEG_STRATEGIES and sid not in BACK_MONTH_STRATEGIES]))
    @settings(max_examples=30, deadline=None)
    def test_fuzz_single_expiry_strategies(strategy_id: str) -> None:
        metrics = build_registry_metrics(
            strategy_id,
            spot=SPOT,
            contracts=FRONT,
            front_expiry=FRONT_EXPIRY,
            iv=0.25,
            ticker=ROOT,
        )
        if metrics and not metrics.get("validation_blocked"):
            spec = STRATEGY_REGISTRY[strategy_id]
            if len(metrics.get("legs") or []) == spec.leg_count:
                result = validate_strategy_output(spec.display_name, metrics, ROOT, spot=SPOT)
                assert result.valid or strategy_id in BACK_MONTH_STRATEGIES

except ImportError:
    pass
