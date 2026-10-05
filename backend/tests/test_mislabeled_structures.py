"""Wheel, poor man's covered call, vega-neutral, and dispersion keep their real shapes."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.strategy_engine import build_strategy_layer, select_strategy
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT = (TODAY + timedelta(days=30)).isoformat()
BACK = (TODAY + timedelta(days=90)).isoformat()
SPOT = 100.0


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(strike * 1000):08d}"


def _quote(
    root: str,
    strike: float,
    side: str,
    expiry: str,
    *,
    bid: float,
    ask: float,
    vega: float | None = None,
) -> dict:
    mid = round((bid + ask) / 2, 2)
    row = {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "expiry": expiry,
        "symbol": _occ(root, expiry, side, strike),
        "delta": 0.55 if side == "call" else -0.45,
        "iv": 0.25,
    }
    if vega is not None:
        row["vega"] = vega
    return row


def _chain(root: str, expiry: str, *, vega: float | None = None) -> list[dict]:
    rows: list[dict] = []
    for strike, call_bid, put_bid in (
        (80.0, 22.0, 0.4),
        (90.0, 12.0, 1.2),
        (95.0, 7.0, 2.4),
        (100.0, 4.0, 3.8),
        (105.0, 2.0, 6.5),
        (110.0, 1.0, 10.0),
        (120.0, 0.4, 18.0),
    ):
        rows.append(_quote(root, strike, "call", expiry, bid=call_bid, ask=call_bid + 0.2, vega=vega))
        rows.append(_quote(root, strike, "put", expiry, bid=put_bid, ask=put_bid + 0.2, vega=vega))
    return rows


def _build(strategy_id: str, **kwargs: object) -> dict:
    metrics = build_registry_metrics(
        strategy_id,
        spot=SPOT,
        contracts=kwargs.pop("contracts", _chain("AAPL", FRONT)),  # type: ignore[arg-type]
        front_expiry=kwargs.pop("front_expiry", FRONT),  # type: ignore[arg-type]
        iv=0.25,
        ticker=kwargs.pop("ticker", "AAPL"),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
    assert metrics is not None
    return metrics


def _option_legs(metrics: dict) -> list[dict]:
    return [leg for leg in metrics.get("legs") or [] if leg.get("side") in {"call", "put"}]


def test_wheel_opens_as_cash_secured_short_put() -> None:
    metrics = _build("wheel_strategy", shares_held=0)
    opts = _option_legs(metrics)
    assert len(opts) == 1
    assert opts[0]["action"] == "sell"
    assert opts[0]["side"] == "put"
    assert float(opts[0]["strike"]) < SPOT
    assert not any(leg.get("side") == "call" for leg in metrics["legs"])
    premium = float(opts[0]["mid"])
    strike = float(opts[0]["strike"])
    assert metrics["max_profit"] == round(premium * 100, 2)
    assert metrics["max_loss"] == round((strike - premium) * 100, 2)
    assert metrics.get("max_loss_unlimited_allowed") is not True
    assert metrics.get("max_profit_unlimited_allowed") is not True
    result = validate_strategy_output("Wheel Strategy", metrics, "AAPL", spot=SPOT)
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]


def test_wheel_covered_call_only_when_shares_are_held() -> None:
    held = _build("wheel_strategy", shares_held=100)
    stock = [leg for leg in held["legs"] if leg.get("side") == "stock"]
    opts = _option_legs(held)
    assert len(stock) == 1 and stock[0]["already_held"] is True and stock[0]["action"] == "buy"
    assert len(opts) == 1
    assert opts[0]["action"] == "sell" and opts[0]["side"] == "call"
    assert float(opts[0]["strike"]) > SPOT
    assert not any(leg.get("side") == "put" for leg in held["legs"])
    result = validate_strategy_output("Wheel Strategy", held, "AAPL", spot=SPOT)
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]

    almost = _build("wheel_strategy", shares_held=99)
    almost_opts = _option_legs(almost)
    assert len(almost_opts) == 1 and almost_opts[0]["side"] == "put"


def test_poor_mans_covered_call_is_a_diagonal_without_finite_max_profit() -> None:
    metrics = _build(
        "poor_mans_covered_call",
        back_month_contracts=_chain("AAPL", BACK),
        back_expiry=BACK,
    )
    opts = _option_legs(metrics)
    assert len(opts) == 2
    long_call = next(leg for leg in opts if leg["action"] == "buy")
    short_call = next(leg for leg in opts if leg["action"] == "sell")
    assert long_call["side"] == "call" and short_call["side"] == "call"
    assert long_call["expiry"] == BACK and short_call["expiry"] == FRONT
    assert float(long_call["strike"]) <= SPOT * 0.90
    assert float(short_call["strike"]) > SPOT
    assert float(short_call["strike"]) > float(long_call["strike"])
    assert metrics["max_profit"] is None
    assert metrics.get("max_profit_unlimited_allowed") is False
    assert metrics.get("payoff_depends_on_remaining_leg") is True
    assert metrics.get("breakevens") == []
    result = validate_strategy_output("Poor Man's Covered Call", metrics, "AAPL", spot=SPOT)
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]


def test_poor_mans_covered_call_does_not_become_a_vertical() -> None:
    metrics = _build("poor_mans_covered_call")
    assert metrics.get("validation_blocked") is True
    assert metrics.get("legs") == []
    assert "diagonal" in str(metrics.get("validation_error")).lower()
    assert "no later expiration" in str(metrics.get("validation_error")).lower()


def test_vega_neutral_uses_two_expirations_at_one_strike() -> None:
    metrics = _build(
        "vega_neutral_spread",
        contracts=_chain("AAPL", FRONT, vega=0.10),
        back_month_contracts=_chain("AAPL", BACK, vega=0.20),
        back_expiry=BACK,
    )
    opts = _option_legs(metrics)
    assert len(opts) == 2
    assert {leg["expiry"] for leg in opts} == {FRONT, BACK}
    assert len({leg["strike"] for leg in opts}) == 1
    buy = next(leg for leg in opts if leg["action"] == "buy")
    sell = next(leg for leg in opts if leg["action"] == "sell")
    assert buy["expiry"] == FRONT and sell["expiry"] == BACK
    assert buy["quantity"] == 2 and sell["quantity"] == 1
    assert metrics["max_profit"] is None
    assert metrics.get("max_profit_unlimited_allowed") is False
    offset = metrics["vega_offset"]
    assert offset["front_quantity"] * offset["front_vega"] == offset["back_quantity"] * offset["back_vega"]
    result = validate_strategy_output("Vega Neutral Spread", metrics, "AAPL", spot=SPOT)
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]


def test_vega_neutral_is_not_a_same_expiry_vertical() -> None:
    metrics = _build("vega_neutral_spread")
    assert metrics.get("validation_blocked") is True
    assert metrics.get("legs") == []
    reason = str(metrics.get("validation_error"))
    assert "vertical was not built" in reason
    assert "two expirations" in reason.lower() or "one expiration" in reason.lower()


def test_dispersion_is_infeasible_on_one_underlying() -> None:
    metrics = _build("dispersion_trade")
    assert metrics.get("validation_blocked") is True
    assert metrics.get("legs") == []
    assert metrics["max_profit"] is None
    reason = str(metrics.get("validation_error"))
    assert "one underlying" in reason
    assert "index" in reason and "component" in reason

    same_name = _build(
        "dispersion_trade",
        component_contracts=_chain("AAPL", FRONT),
        component_ticker="AAPL",
    )
    assert same_name.get("legs") == []
    assert same_name.get("validation_blocked") is True


def test_dispersion_uses_a_second_underlying_when_one_is_supplied() -> None:
    metrics = _build(
        "dispersion_trade",
        ticker="SPY",
        contracts=_chain("SPY", FRONT),
        component_contracts=_chain("AAPL", FRONT),
        component_ticker="AAPL",
    )
    opts = _option_legs(metrics)
    assert len(opts) == 2
    short_call = next(leg for leg in opts if leg["action"] == "sell")
    long_call = next(leg for leg in opts if leg["action"] == "buy")
    assert short_call["underlying"] == "SPY"
    assert long_call["underlying"] == "AAPL"
    assert short_call["symbol"] != long_call["symbol"]
    assert metrics["max_profit"] is None
    assert metrics.get("max_profit_unlimited_allowed") is False


def test_single_name_scan_does_not_return_dispersion_as_best_match() -> None:
    for direction, vol in (("bullish", "buy_premium"), ("bearish", "buy_premium"), ("neutral", "sell_premium")):
        name = select_strategy(
            composite=80.0,
            direction=direction,
            vol_signal=vol,
            rsi=50.0,
            iv=0.20,
            hv=0.35,
            tech_score=85.0,
            symbol="AAPL",
            spot=SPOT,
        )
        assert name != "Dispersion Trade"

    layer = build_strategy_layer(
        strategy_name="Dispersion Trade",
        composite=80.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={"symbol": "AAPL", "spot": SPOT, "expiry": FRONT, "contracts": _chain("AAPL", FRONT)},
        vol_layer={"iv": 0.30, "hv": 0.20, "iv_rank": 60},
        sentiment_layer={"bias": "neutral", "score_0_100": 50},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        ticker="AAPL",
    )
    assert layer["tradeable"] is False
    assert layer["metrics"].get("legs") == []
    text = f"{layer['what_is_this']} {layer['how_to_execute']}".lower()
    assert "one underlying" in text
    assert "vertical" not in text
