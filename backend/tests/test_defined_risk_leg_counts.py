"""Built structures match the registry leg count, or they are not built."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.strategies.exceptions import StrategyValidationError
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT = (TODAY + timedelta(days=30)).isoformat()
BACK = (TODAY + timedelta(days=60)).isoformat()

AUDITED = (
    "short_iron_condor",
    "long_iron_condor",
    "iron_condor_wide",
    "reverse_iron_condor",
    "iv_crush_short_iron_condor",
    "theta_harvest_iron_condor",
    "iron_condor_monthly",
    "iron_butterfly",
    "long_iron_butterfly",
    "condor_spread_call",
    "condor_spread_put",
    "bull_call_spread",
    "bear_put_spread",
    "bull_put_spread_credit",
    "bear_call_spread_credit",
    "call_debit_spread",
    "put_debit_spread",
    "long_straddle",
    "short_straddle",
    "long_strangle",
    "short_strangle",
    "calendar_spread",
    "diagonal_spread_bullish",
    "diagonal_spread_bearish",
    "double_calendar",
    "double_diagonal",
    "apex_strategy",
)


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(round(strike * 1000)):08d}"


def _chain(spot: float, expiry: str, strikes: list[float], *, delta: bool = True) -> list[dict]:
    rows: list[dict] = []
    for strike in strikes:
        call_delta = round(max(0.05, min(0.95, 0.50 - (strike - spot) / (spot * 0.5))), 2)
        put_delta = round(-call_delta, 2)
        dist = abs(strike - spot)
        call_bid = max(0.30, 6.0 - dist * 0.08)
        put_bid = max(0.30, 5.5 - dist * 0.07)
        for side, greek, bid in (("call", call_delta, call_bid), ("put", put_delta, put_bid)):
            rows.append(
                {
                    "side": side,
                    "strike": strike,
                    "bid": bid,
                    "ask": round(bid + 0.10, 2),
                    "last": round(bid + 0.05, 2),
                    "symbol": _occ("TSLA", expiry, side, strike),
                    "expiry": expiry,
                    "delta": greek if delta else None,
                    "iv": 0.45,
                }
            )
    return rows


def _build(strategy_id: str, contracts: list[dict], *, back: list[dict] | None = None) -> dict:
    return build_registry_metrics(
        strategy_id,
        spot=250.0,
        contracts=contracts,
        back_month_contracts=back,
        front_expiry=FRONT,
        back_expiry=BACK if back else None,
        iv=0.45,
        ticker="TSLA",
        recommended={"strike": 250.0, "side": "call", "expiry": FRONT},
    )


@pytest.mark.parametrize("strategy_id", AUDITED)
def test_audited_structure_matches_registry_leg_count(strategy_id: str) -> None:
    strikes = [200.0, 220.0, 230.0, 240.0, 250.0, 260.0, 270.0, 280.0, 300.0]
    front = _chain(250.0, FRONT, strikes)
    back = _chain(250.0, BACK, strikes)
    metrics = _build(strategy_id, front, back=back)
    spec = STRATEGY_REGISTRY[strategy_id]
    assert metrics is not None
    legs = metrics.get("legs") or []
    assert not metrics.get("validation_blocked"), metrics.get("validation_error")
    assert len(legs) == spec.leg_count
    result = validate_strategy_output(spec.display_name, metrics, "TSLA", spot=250.0)
    assert not any(err.check == "leg_count" for err in result.errors)


def test_short_iron_condor_without_deltas_still_has_four_legs() -> None:
    """Missing deltas used to pin the short on the first strike and drop the wing."""
    strikes = [200.0, 220.0, 240.0, 250.0, 260.0, 280.0, 300.0]
    metrics = _build("short_iron_condor", _chain(250.0, FRONT, strikes, delta=False))
    legs = metrics.get("legs") or []
    assert len(legs) == 4
    assert not metrics.get("validation_blocked")
    sides = sorted((leg["action"], leg["side"]) for leg in legs)
    assert sides == [("buy", "call"), ("buy", "put"), ("sell", "call"), ("sell", "put")]
    result = validate_strategy_output("Short Iron Condor", metrics, "TSLA", spot=250.0)
    assert not any(err.check == "leg_count" for err in result.errors)
    assert result.valid, [(err.check, err.expected, err.actual) for err in result.errors]


def test_short_iron_condor_skips_the_chain_edge_when_an_inner_wing_is_quoted() -> None:
    """The 0.05-delta strikes are the chain edge. The 0.20-delta strikes still have wings."""

    def row(strike: float, side: str, greek: float, bid: float) -> dict:
        return {
            "side": side,
            "strike": strike,
            "delta": greek,
            "bid": bid,
            "ask": bid + 0.1,
            "symbol": _occ("TSLA", FRONT, side, strike),
            "expiry": FRONT,
        }

    contracts = [
        row(230.0, "put", -0.05, 0.40),
        row(240.0, "put", -0.20, 1.20),
        row(250.0, "put", -0.50, 3.00),
        row(250.0, "call", 0.50, 3.10),
        row(260.0, "call", 0.20, 1.10),
        row(270.0, "call", 0.05, 0.35),
    ]
    metrics = _build("short_iron_condor", contracts)
    legs = metrics.get("legs") or []
    assert len(legs) == 4
    puts = {leg["action"]: leg["strike"] for leg in legs if leg["side"] == "put"}
    calls = {leg["action"]: leg["strike"] for leg in legs if leg["side"] == "call"}
    assert puts["buy"] < puts["sell"]
    assert calls["sell"] < calls["buy"]
    assert puts["sell"] == 240.0
    assert calls["sell"] == 260.0


def test_missing_wing_quote_does_not_emit_a_three_leg_condor() -> None:
    contracts = [
        {"side": "put", "strike": 240.0, "delta": -0.20, "bid": 1.4, "ask": 1.6, "symbol": _occ("TSLA", FRONT, "put", 240.0), "expiry": FRONT},
        {"side": "call", "strike": 260.0, "delta": 0.20, "bid": 1.2, "ask": 1.4, "symbol": _occ("TSLA", FRONT, "call", 260.0), "expiry": FRONT},
    ]
    metrics = _build("short_iron_condor", contracts)
    assert metrics.get("legs") == []
    assert metrics.get("validation_blocked") is True
    reason = str(metrics.get("validation_error"))
    assert "wing" in reason.lower()
    assert "{" not in reason
    assert "strategy_id" not in reason


def test_validation_failure_is_a_sentence_not_a_dict() -> None:
    message = StrategyValidationError(
        strategy_id="short_iron_condor",
        ticker="TSLA",
        check="leg_count",
        expected="4",
        actual="3",
    ).trader_message()
    assert message == (
        "Short Iron Condor on TSLA failed the leg count check: expected 4, got 3. "
        "This is not the strategy on the card."
    )
    assert "{" not in message
