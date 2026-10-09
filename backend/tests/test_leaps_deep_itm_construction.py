"""LEAPS expiries are far-dated, and deep-ITM strikes are well in the money."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.strategies.chain_utils import dte_from_expiry
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.registry import get_strategy_spec

SPOT = 100.0
TODAY = datetime.now(timezone.utc).date()
FRONT_EXPIRY = (TODAY + timedelta(days=14)).isoformat()
NEAR_BACK_EXPIRY = (TODAY + timedelta(days=60)).isoformat()
LEAPS_EXPIRY = (TODAY + timedelta(days=400)).isoformat()


def _contract(strike: float, side: str, expiry: str, *, delta: float) -> dict:
    distance = abs(strike - SPOT)
    bid = max(0.40, 6.0 - distance * 0.08)
    return {
        "side": side,
        "strike": strike,
        "expiry": expiry,
        "bid": bid,
        "ask": bid + 0.20,
        "last": bid + 0.10,
        "delta": delta,
        "iv": 0.25,
        "symbol": f"TEST{expiry.replace('-', '')[2:]}{'C' if side == 'call' else 'P'}{int(strike * 1000):08d}",
    }


def _chain(expiry: str) -> list[dict]:
    rows: list[dict] = []
    for strike, call_delta, put_delta in (
        (70.0, 0.95, -0.05),
        (80.0, 0.90, -0.10),
        (90.0, 0.75, -0.25),
        (100.0, 0.52, -0.48),
        (110.0, 0.28, -0.72),
        (120.0, 0.12, -0.88),
        (130.0, 0.05, -0.95),
    ):
        rows.append(_contract(strike, "call", expiry, delta=call_delta))
        rows.append(_contract(strike, "put", expiry, delta=put_delta))
    return rows


CHAIN = _chain(FRONT_EXPIRY) + _chain(NEAR_BACK_EXPIRY) + _chain(LEAPS_EXPIRY)


def _metrics(strategy_id: str) -> dict:
    metrics = build_registry_metrics(
        strategy_id,
        spot=SPOT,
        contracts=CHAIN,
        front_expiry=FRONT_EXPIRY,
        back_expiry=NEAR_BACK_EXPIRY,
        iv=0.25,
        ticker="TEST",
        recommended={"strike": SPOT, "side": "call", "expiry": FRONT_EXPIRY},
    )
    assert metrics is not None
    assert not metrics.get("validation_blocked"), metrics.get("validation_error")
    return metrics


def test_leaps_expiry_is_farther_than_the_front_and_deep_itm_is_in_the_money() -> None:
    front_dte = dte_from_expiry(FRONT_EXPIRY)
    leaps_dte = dte_from_expiry(LEAPS_EXPIRY)
    assert front_dte is not None and leaps_dte is not None
    assert leaps_dte > front_dte
    assert leaps_dte > 365

    for strategy_id in ("long_call_leaps", "long_put_leaps", "long_straddle_leaps"):
        legs = _metrics(strategy_id)["legs"]
        assert legs, strategy_id
        for leg in legs:
            assert leg["expiry"] == LEAPS_EXPIRY, strategy_id
            assert leg["expiry"] != FRONT_EXPIRY
            leg_dte = dte_from_expiry(str(leg["expiry"]))
            assert leg_dte is not None and leg_dte > front_dte

    call_spec = get_strategy_spec("deep_itm_call")
    put_spec = get_strategy_spec("deep_itm_put")
    atm_spec = get_strategy_spec("atm_call")
    assert call_spec is not None and put_spec is not None and atm_spec is not None
    assert call_spec.leg_specs[0].strike_relationship == "deep_itm"
    assert put_spec.leg_specs[0].strike_relationship == "deep_itm"
    assert atm_spec.leg_specs[0].strike_relationship != "deep_itm"

    deep_call = _metrics("deep_itm_call")["legs"][0]
    deep_put = _metrics("deep_itm_put")["legs"][0]
    atm_call = _metrics("atm_call")["legs"][0]

    assert float(deep_call["strike"]) <= SPOT * 0.90 + 1e-6
    assert SPOT - float(deep_call["strike"]) >= SPOT * 0.10 - 1e-6
    assert float(deep_put["strike"]) >= SPOT * 1.10 - 1e-6
    assert float(deep_put["strike"]) - SPOT >= SPOT * 0.10 - 1e-6
    assert abs(float(atm_call["strike"]) - SPOT) <= SPOT * 0.05
