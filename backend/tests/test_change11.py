"""Change 11: APEX Benchmark Greeks Strategy and Gamma Trampoline™."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.analysis.black_scholes import greeks, year_fraction
from app.analysis.gate_config import apex_delta_theta_ratio
from app.database import Base
from app.models.user import User
from app.schemas.market import Quote
from app.services.apex_strategy import (
    DOUBLE_CALENDAR_NAME,
    GAMMA_TRAMPOLINE_NAME,
    ApexStrategyInput,
    check_apex_strategy_eligibility,
    classifier_label,
)
from app.services.benchmark_greeks import evaluate_rule1, evaluate_rule2
from app.services.fills import execute_strategy_legs
from app.services.strategy_engine import build_strategy_layer
from app.services.strategy_recommendation import (
    MarketSnapshot,
    TechnicalAnalysisResultRef,
    recommend_strategy,
)
from app.strategies.knowledge_base import (
    BENCHMARK_SUMMARY,
    GAMMA_GREEKS,
    GAMMA_HOW,
    GAMMA_PROBLEM,
    GAMMA_SCENARIOS,
    GAMMA_SUMMARY,
    RULE1_HOW,
    RULE1_RATIO,
    RULE1_RISKS,
    RULE1_WHY,
    RULE2_HOW,
    RULE2_PROBABILITY,
    RULE2_RISKS,
    RULE2_WHY,
)
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.payoffs.core import (
    apex_strategy_payoff,
    gamma_move_table,
    iron_condor_payoff,
    vertical_credit_payoff,
)
from app.strategies.registry import STRATEGY_REGISTRY

TODAY = date.today()
FRONT = (TODAY + timedelta(days=7)).isoformat()
BACK = (TODAY + timedelta(days=21)).isoformat()


def _rule1(**overrides: object):
    payload = dict(
        technical_direction="bullish",
        sentiment_score=70.0,
        sentiment_bias="bullish",
        delta=0.60,
        spot=250.0,
        theta_per_share=0.08,
        mid=20.0,
        dte=45,
        contract_iv=0.20,
        hv20=0.30,
        bid=19.8,
        ask=20.2,
    )
    payload.update(overrides)
    return evaluate_rule1(**payload)  # type: ignore[arg-type]


def _quote(strike: float, side: str, delta: float, bid: float, ask: float) -> dict:
    return {"side": side, "strike": strike, "delta": delta, "bid": bid, "ask": ask}


def _rule2_chain() -> list[dict]:
    """Wing width 3, about 3% of a 100 spot. Short absolute delta 0.18."""
    return [
        _quote(92, "put", -0.10, 0.40, 0.44),
        _quote(95, "put", -0.18, 1.20, 1.26),
        _quote(105, "call", 0.18, 1.20, 1.26),
        _quote(108, "call", 0.10, 0.40, 0.44),
    ]


def _rule2(**overrides: object):
    payload = dict(
        technical_direction="neutral",
        sentiment_score=50.0,
        sentiment_bias="neutral",
        iv_rank=60.0,
        rsi=50.0,
        dte=35,
        contracts=_rule2_chain(),
        spot=100.0,
    )
    payload.update(overrides)
    return evaluate_rule2(**payload)  # type: ignore[arg-type]


def _gamma_input(**overrides: object) -> ApexStrategyInput:
    payload = dict(
        catalyst_days=7,
        front_iv=0.55,
        back_iv=0.36,
        front_ivr=80.0,
        four_leg_structure=True,
        legs_same_strikes=True,
        adv=6_000_000,
        open_interest=2000,
        spread_pct=4.0,
        earnings_date_confirmed=True,
        earnings_history_hits=6,
        earnings_history_count=8,
        front_expiry_listed=True,
        back_expiry_listed=True,
    )
    payload.update(overrides)
    return ApexStrategyInput(**payload)  # type: ignore[arg-type]


def _rank(**kwargs: object):
    direction = str(kwargs.pop("direction"))
    composite = float(kwargs.pop("composite", 80.0))
    tech = float(kwargs.pop("tech", 70.0))
    return recommend_strategy(
        market=MarketSnapshot(
            symbol="AAPL",
            spot=float(kwargs.pop("market_spot", 100.0)),
            direction=direction,  # type: ignore[arg-type]
            data_fresh=True,
            adv=6_000_000,
        ),
        technical=TechnicalAnalysisResultRef(score=tech, direction=direction, confirmed_pattern_count=1),
        composite=composite,
        vol_signal=str(kwargs.pop("vol_signal", "fair")),
        rsi=kwargs.pop("rsi", 50.0),  # type: ignore[arg-type]
        iv=kwargs.pop("iv", 0.20),  # type: ignore[arg-type]
        hv=kwargs.pop("hv", 0.40),  # type: ignore[arg-type]
        ivr=kwargs.pop("ivr", 40.0),  # type: ignore[arg-type]
        sentiment_score=kwargs.pop("sentiment_score", None),  # type: ignore[arg-type]
        sentiment_bias=kwargs.pop("sentiment_bias", None),  # type: ignore[arg-type]
        catalyst_active=bool(kwargs.pop("catalyst_active", False)),
        apex_input=kwargs.pop("apex_input", None),  # type: ignore[arg-type]
        risk_profile="moderate",
        rule_context=kwargs.pop("rule_context", None),  # type: ignore[arg-type]
    )


def test_rule1_ratio_hand_values() -> None:
    passing = apex_delta_theta_ratio(0.60, 250.0, 0.08)
    failing = apex_delta_theta_ratio(-0.60, 250.0, 0.20)
    assert passing == pytest.approx(18.75)
    assert failing == pytest.approx(7.5)
    assert _rule1().eligible is True
    missed = _rule1(theta_per_share=0.20)
    assert missed.eligible is False
    assert any("APEX Delta/Theta Ratio 7.50 is not above 10" in reason for reason in missed.reasons)


def test_rule1_bullish_call_and_bearish_put() -> None:
    bull = _rule1()
    assert bull.eligible is True
    assert bull.side == "call"
    assert bull.structure == "long_option"
    bear = _rule1(
        technical_direction="bearish",
        sentiment_score=30.0,
        sentiment_bias="bearish",
        delta=-0.60,
    )
    assert bear.eligible is True
    assert bear.side == "put"
    assert any("Absolute delta 0.60" in line for line in bear.passed)


@pytest.mark.parametrize(
    ("overrides", "snippet"),
    [
        ({"technical_direction": "neutral", "sentiment_score": 50.0, "sentiment_bias": "neutral"}, "Directional alignment failed"),
        ({"delta": 0.50}, "Absolute delta 0.50 is below 0.55"),
        ({"delta": -0.50, "technical_direction": "bearish", "sentiment_score": 30.0, "sentiment_bias": "bearish"}, "Absolute delta 0.50 is below 0.55"),
        ({"dte": 20}, "DTE 20 is outside 30 to 90"),
        ({"theta_per_share": 0.25, "mid": 20.0}, "Daily theta is 1.25% of the mid"),
        ({"theta_per_share": 0.20}, "APEX Delta/Theta Ratio 7.50 is not above 10"),
        ({"contract_iv": 0.40, "hv20": 0.30}, "Option IV 0.4000 is not below 20-day historical volatility 0.3000"),
        ({"bid": 19.0, "ask": 21.0}, "Bid/ask spread is 10.0% of mid, not below 8%"),
    ],
)
def test_rule1_each_gate_fails_alone(overrides: dict, snippet: str) -> None:
    result = _rule1(**overrides)
    assert result.eligible is False
    assert any(snippet in reason for reason in result.reasons)


def test_rule2_structures_are_defined_risk() -> None:
    condor = _rule2()
    assert condor.eligible is True
    assert condor.structure == "iron_condor"
    assert [leg["action"] for leg in condor.legs] == ["sell", "buy", "sell", "buy"]
    assert len(condor.legs) == 4
    bull = _rule2(technical_direction="bullish", sentiment_score=55.0, sentiment_bias="bullish")
    assert bull.eligible is True
    assert bull.structure == "bull_put"
    assert [leg["side"] for leg in bull.legs] == ["put", "put"]
    assert bull.legs[0]["action"] == "sell" and bull.legs[1]["action"] == "buy"
    bear = _rule2(technical_direction="bearish", sentiment_score=50.0, sentiment_bias="neutral")
    assert bear.eligible is True
    assert bear.structure == "bear_call"
    assert [leg["side"] for leg in bear.legs] == ["call", "call"]


@pytest.mark.parametrize(
    ("overrides", "snippet"),
    [
        ({"iv_rank": 45}, "IV Rank 45 is not above 50"),
        ({"rsi": 35}, "RSI(14) 35 is outside 40 to 60"),
        ({"rsi": 65}, "RSI(14) 65 is outside 40 to 60"),
        (
            {
                "contracts": [
                    _quote(95, "put", -0.25, 1.10, 1.20),
                    _quote(92, "put", -0.25, 0.30, 0.36),
                    _quote(105, "call", 0.25, 1.10, 1.20),
                    _quote(108, "call", 0.25, 0.30, 0.36),
                ]
            },
            "absolute delta at or below 0.20",
        ),
        (
            {
                "contracts": [
                    _quote(92, "put", -0.10, 0.30, 0.36),
                    _quote(95, "put", -0.18, 0.94, 1.06),
                    _quote(105, "call", 0.18, 1.10, 1.20),
                    _quote(108, "call", 0.10, 0.30, 0.36),
                ]
            },
            "Bid/ask spread on sell put 95 is 12.0% of mid, not below 10%",
        ),
        (
            {
                "contracts": [
                    _quote(92, "put", -0.10, 0.70, 0.76),
                    _quote(95, "put", -0.18, 0.90, 0.96),
                    _quote(105, "call", 0.18, 0.90, 0.96),
                    _quote(108, "call", 0.10, 0.70, 0.76),
                ]
            },
            "Net credit",
        ),
    ],
)
def test_rule2_each_rejection(overrides: dict, snippet: str) -> None:
    result = _rule2(**overrides)
    assert result.eligible is False
    assert result.legs == []
    assert any(snippet in reason for reason in result.reasons)
    assert not any(leg.get("action") == "sell" and "wing" not in reason.lower() for leg in result.legs for reason in [])


def test_rule2_never_returns_a_naked_short() -> None:
    result = _rule2(contracts=[_quote(95, "put", -0.18, 1.10, 1.20), _quote(105, "call", 0.18, 1.10, 1.20)])
    assert result.eligible is False
    assert result.legs == []
    assert any("naked short" in reason for reason in result.reasons)


def test_rule2_credit_and_condor_math_matches_hand_values() -> None:
    put_spread = vertical_credit_payoff(short_strike=100, long_strike=95, net_credit=1.50, side="put", contract_multiplier=100)
    assert put_spread["max_profit"] == 150.0
    assert put_spread["max_loss"] == 350.0
    assert put_spread["breakevens"] == [98.5]
    two = vertical_credit_payoff(short_strike=100, long_strike=95, net_credit=1.50, side="put", contract_multiplier=200)
    assert two["max_profit"] == 300.0
    assert two["max_loss"] == 700.0
    call_spread = vertical_credit_payoff(short_strike=110, long_strike=115, net_credit=0.80, side="call", contract_multiplier=100)
    assert call_spread["max_profit"] == 80.0
    assert call_spread["max_loss"] == 420.0
    assert call_spread["breakevens"] == [110.8]
    condor = iron_condor_payoff(
        short_put_strike=95, long_put_strike=90, short_call_strike=105, long_call_strike=110, net_credit=1.80
    )
    assert condor["max_profit"] == 180.0
    assert condor["max_loss"] == 320.0
    assert condor["breakevens"] == [93.2, 106.8]
    wider = iron_condor_payoff(
        short_put_strike=95, long_put_strike=90, short_call_strike=105, long_call_strike=115, net_credit=2.0, contract_multiplier=300
    )
    assert wider["max_profit"] == 600.0
    assert wider["max_loss"] == 2400.0
    assert wider["breakevens"] == [93.0, 107.0]


def test_failed_rule_does_not_replace_the_card_with_no_trade() -> None:
    decision = _rank(
        direction="bullish",
        sentiment_score=70.0,
        sentiment_bias="bullish",
        rule_context={
            "technical_direction": "bullish",
            "sentiment_score": 70.0,
            "sentiment_bias": "bullish",
            "delta": 0.40,
            "spot": 100.0,
            "theta_per_share": 0.08,
            "mid": 10.0,
            "dte": 45,
            "contract_iv": 0.20,
            "hv20": 0.30,
            "bid": 9.9,
            "ask": 10.1,
        },
    )
    stand_aside = {spec.display_name for spec in STRATEGY_REGISTRY.values() if spec.leg_count == 0}
    assert decision.best_match not in stand_aside
    assert "IV Crush" not in decision.best_match
    held = next(row for row in decision.candidates if row.name == "APEX Benchmark Greeks Strategy")
    assert held.eligible is False
    assert any("Absolute delta 0.40 is below 0.55" in note for note in held.gate_notes)


def _rule1_context(spot: float, delta: float, theta: float, *, bearish: bool = False) -> dict:
    return {
        "technical_direction": "bearish" if bearish else "bullish",
        "sentiment_score": 30.0 if bearish else 72.0,
        "sentiment_bias": "bearish" if bearish else "bullish",
        "delta": -abs(delta) if bearish else abs(delta),
        "spot": spot,
        "theta_per_share": theta,
        "mid": 20.0,
        "dte": 45,
        "contract_iv": 0.20,
        "hv20": 0.35,
        "bid": 19.9,
        "ask": 20.1,
    }


@pytest.mark.parametrize(
    ("spot", "delta", "theta", "composite", "bearish"),
    [
        (100.0, 0.60, 0.05, 72.0, False),
        (150.0, 0.62, 0.08, 78.0, False),
        (200.0, 0.70, 0.10, 84.0, False),
        (250.0, 0.60, 0.08, 88.0, True),
        (300.0, 0.65, 0.12, 90.0, True),
    ],
)
def test_rule1_ranks_first_in_purpose_built_scans(spot: float, delta: float, theta: float, composite: float, bearish: bool) -> None:
    decision = _rank(
        direction="bearish" if bearish else "bullish",
        composite=composite,
        sentiment_score=30.0 if bearish else 72.0,
        sentiment_bias="bearish" if bearish else "bullish",
        iv=0.20,
        hv=0.40,
        ivr=40.0,
        rule_context=_rule1_context(spot, delta, theta, bearish=bearish),
        market_spot=spot,
    )
    assert decision.best_match == "APEX Benchmark Greeks Strategy"
    eligible = [row for row in decision.candidates if row.eligible]
    assert eligible[0].name == "APEX Benchmark Greeks Strategy"


@pytest.mark.parametrize("rsi,iv_rank", [(42, 55), (48, 62), (50, 70), (55, 80), (58, 90)])
def test_rule2_neutral_ranks_iron_condor_first(rsi: float, iv_rank: float) -> None:
    decision = _rank(
        direction="neutral",
        sentiment_score=50.0,
        sentiment_bias="neutral",
        rsi=rsi,
        iv=0.40,
        hv=0.25,
        ivr=iv_rank,
        vol_signal="sell_premium",
        rule_context={
            "technical_direction": "neutral",
            "sentiment_score": 50.0,
            "sentiment_bias": "neutral",
            "iv_rank": iv_rank,
            "rsi": rsi,
            "rule2_dte": 35,
            "contracts": _rule2_chain(),
            "spot": 100.0,
        },
    )
    assert decision.best_match == "Short Iron Condor"
    winner = next(row for row in decision.candidates if row.name == "Short Iron Condor" and row.eligible)
    assert any("APEX Benchmark Greeks Strategy Rule 2" in note for note in winner.gate_notes)


def test_rule2_mild_bias_ranks_the_credit_spread() -> None:
    bull = _rank(
        direction="bullish",
        sentiment_score=55.0,
        sentiment_bias="bullish",
        rsi=50.0,
        iv=0.40,
        hv=0.25,
        ivr=60.0,
        vol_signal="sell_premium",
        rule_context={
            "technical_direction": "bullish",
            "sentiment_score": 55.0,
            "sentiment_bias": "bullish",
            "iv_rank": 60.0,
            "rsi": 50.0,
            "rule2_dte": 35,
            "contracts": _rule2_chain(),
            "spot": 100.0,
        },
    )
    assert bull.best_match == "Bull Put Spread (credit)"
    bear = _rank(
        direction="bearish",
        sentiment_score=50.0,
        sentiment_bias="neutral",
        rsi=50.0,
        iv=0.40,
        hv=0.25,
        ivr=60.0,
        vol_signal="sell_premium",
        rule_context={
            "technical_direction": "bearish",
            "sentiment_score": 50.0,
            "sentiment_bias": "neutral",
            "iv_rank": 60.0,
            "rsi": 50.0,
            "rule2_dte": 35,
            "contracts": _rule2_chain(),
            "spot": 100.0,
        },
    )
    assert bear.best_match == "Bear Call Spread (credit)"


def test_rule1_card_uses_the_knowledge_base_text() -> None:
    layer = build_strategy_layer(
        strategy_name="APEX Benchmark Greeks Strategy",
        composite=88.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={
            "contracts": [
                {
                    "side": "call",
                    "strike": 100.0,
                    "delta": 0.60,
                    "bid": 4.8,
                    "ask": 5.0,
                    "expiry": (TODAY + timedelta(days=45)).isoformat(),
                    "symbol": "AAPL251114C00100000",
                    "iv": 0.20,
                }
            ],
            "expiry": (TODAY + timedelta(days=45)).isoformat(),
            "recommendedContract": {"side": "call", "strike": 100.0},
        },
        vol_layer={"hv": 0.30, "iv": 0.20},
        sentiment_layer={"score_0_100": 72, "bias": "bullish"},
        fundamentals_layer={},
        tech_score=70.0,
        ticker="AAPL",
    )
    text = f"{layer['what_is_this']} {layer['why_it_fits']} {layer['how_to_execute']} {' '.join(layer['risk_notes'])}"
    for sentence in (BENCHMARK_SUMMARY, RULE1_WHY, RULE1_RATIO, RULE1_HOW, RULE1_RISKS):
        assert sentence in text


def _occ(expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"AAPL{yymmdd}{cp}{int(round(strike * 1000)):08d}"


def _priced_chain() -> tuple[list[dict], list[dict], float]:
    spot = 100.0
    front_iv, back_iv = 0.55, 0.36
    front_years, back_years = year_fraction(7), year_fraction(21)
    front_rows: list[dict] = []
    back_rows: list[dict] = []
    for strike in range(80, 121):
        for side in ("call", "put"):
            for years, vol, expiry, bucket in (
                (front_years, front_iv, FRONT, front_rows),
                (back_years, back_iv, BACK, back_rows),
            ):
                model = greeks(spot=spot, strike=float(strike), years=years, vol=vol, side=side)
                assert model is not None
                price = max(model.price, 0.05)
                bucket.append(
                    {
                        "side": side,
                        "strike": float(strike),
                        "bid": round(price * 0.995, 4),
                        "ask": round(price * 1.005, 4),
                        "symbol": _occ(expiry, side, strike),
                        "expiry": expiry,
                        "delta": model.delta,
                        "gamma": model.gamma,
                        "theta": model.theta,
                        "vega": model.vega,
                        "iv": vol,
                        "open_interest": 2500,
                    }
                )
    atm_call = greeks(spot=spot, strike=100, years=front_years, vol=front_iv, side="call")
    atm_put = greeks(spot=spot, strike=100, years=front_years, vol=front_iv, side="put")
    assert atm_call and atm_put
    return front_rows, back_rows, atm_call.price + atm_put.price


def test_gamma_eligible_structure_and_simulation() -> None:
    front_rows, back_rows, expected_move = _priced_chain()
    metrics = build_registry_metrics(
        "apex_strategy",
        spot=100.0,
        contracts=front_rows,
        back_month_contracts=back_rows,
        front_expiry=FRONT,
        back_expiry=BACK,
        iv=0.55,
        hv=0.28,
        ticker="AAPL",
    )
    assert metrics is not None
    assert metrics.get("validation_blocked") is not True
    legs = metrics["legs"]
    assert len(legs) == 4
    calls = [leg for leg in legs if leg["side"] == "call"]
    puts = [leg for leg in legs if leg["side"] == "put"]
    assert len({leg["strike"] for leg in calls}) == 1
    assert len({leg["strike"] for leg in puts}) == 1
    assert {leg["expiry"] for leg in legs if leg["action"] == "sell"} == {FRONT}
    assert {leg["expiry"] for leg in legs if leg["action"] == "buy"} == {BACK}
    assert metrics["scenario_conflict"] is None
    assert metrics["pricing_model"] == "european_black_scholes"
    assert "European Black-Scholes" in metrics["payoff_notes"]
    assert "does not have an American pricer" in metrics["payoff_notes"]
    assert metrics["premium_offset_pct"] > 0
    debit = float(metrics["net_debit_credit"])
    assert metrics["max_loss"] == pytest.approx(round(abs(debit) * 100, 2), abs=0.01)
    call_strike = float(calls[0]["strike"])
    put_strike = float(puts[0]["strike"])
    table = gamma_move_table(
        spot=100.0,
        call_strike=call_strike,
        put_strike=put_strike,
        net_debit=debit,
        front_dte_days=7,
        back_dte_days=21,
        post_event_iv=0.28,
        expected_move=expected_move,
    )
    rows = {row["move"]: row["pnl"] for row in table["rows"]["1.00"]}
    near = max(rows[1.0], rows[-1.0])
    assert near > rows[0.0]
    assert near > rows[0.5] and near > rows[-0.5]
    assert near > rows[2.0] and near > rows[-2.0]
    assert rows[0.0] > 0
    assert rows[2.0] < 0 and rows[-2.0] < 0
    assert rows[2.0] >= -metrics["max_loss"] - 0.01
    assert rows[-2.0] >= -metrics["max_loss"] - 0.01
    assert metrics["greeks"]["gamma"] < 0
    remaining = year_fraction(14)
    after = greeks(spot=100, strike=call_strike, years=remaining, vol=0.28, side="call")
    after_put = greeks(spot=100, strike=put_strike, years=remaining, vol=0.28, side="put")
    assert after and after_put
    assert after.gamma + after_put.gamma > 0
    priced = apex_strategy_payoff(
        spot=100.0,
        call_strike=call_strike,
        put_strike=put_strike,
        net_debit=debit,
        front_dte_days=7,
        back_dte_days=21,
        iv=0.36,
        post_event_iv=0.28,
        expected_move=expected_move,
    )
    assert priced["scenario_conflict"] is None
    assert len(priced["breakevens"]) == 2
    assert priced["probability_of_profit"] is not None


def test_gamma_sensitivity_shifts_breakevens_and_max_profit() -> None:
    _front, _back, expected_move = _priced_chain()
    table = gamma_move_table(
        spot=100.0,
        call_strike=106,
        put_strike=94,
        net_debit=0.6172,
        front_dte_days=7,
        back_dte_days=21,
        post_event_iv=0.28,
        expected_move=expected_move,
    )
    half, full, more = table["summary"]["0.50"], table["summary"]["1.00"], table["summary"]["1.50"]
    assert half["max_profit"] < full["max_profit"] < more["max_profit"]
    assert min(full["breakevens"]) > min(more["breakevens"])
    assert max(full["breakevens"]) < max(more["breakevens"])
    assert half["min_pnl"] == pytest.approx(-61.72, abs=0.02)
    assert full["min_pnl"] == pytest.approx(-61.72, abs=0.02)


@pytest.mark.parametrize(
    ("overrides", "snippet"),
    [
        ({"earnings_date_confirmed": False}, "Earnings date is missing."),
        ({"catalyst_days": 3}, "Calendar days to confirmed earnings 3 is outside 5 to 10."),
        ({"front_ivr": 70}, "Front-week IV rank 70 is not above 70."),
        ({"front_iv": 0.40, "back_iv": 0.40}, "Front-week IV divided by back-week IV is 1.00, below 1.25."),
        ({"earnings_history_hits": None, "earnings_history_count": None}, "Earnings move history is missing; the last 8 reports are not in the data."),
        ({"earnings_history_hits": 4, "earnings_history_count": 8}, "Only 4 of the last 8 earnings moves"),
        ({"adv": 5_000_000}, "ADV 5,000,000 is not above 5,000,000 shares."),
        ({"open_interest": 1000}, "Open interest 1000 is not above 1000."),
        ({"spread_pct": 8.0}, "Bid/ask spread is 8.0% of mid, not below 8%."),
        ({"front_expiry_listed": False}, "front expiry after earnings and a back expiry about 2 weeks later"),
    ],
)
def test_gamma_each_gate_fails_alone(overrides: dict, snippet: str) -> None:
    result = check_apex_strategy_eligibility(_gamma_input(**overrides))
    assert result.eligible is False
    assert result.strategy_name == DOUBLE_CALENDAR_NAME
    assert any(snippet in reason for reason in result.rejection_reasons)


def test_classifier_uses_the_trademark_only_when_gates_pass() -> None:
    assert classifier_label(eligible=True) == GAMMA_TRAMPOLINE_NAME
    assert classifier_label(eligible=False) == DOUBLE_CALENDAR_NAME
    passed = check_apex_strategy_eligibility(_gamma_input())
    assert passed.eligible is True
    assert passed.strategy_name == GAMMA_TRAMPOLINE_NAME
    missed = check_apex_strategy_eligibility(_gamma_input(earnings_date_confirmed=False))
    assert missed.strategy_name == DOUBLE_CALENDAR_NAME


@pytest.mark.parametrize("days", [5, 6, 7, 8, 10])
def test_gamma_ranks_first_when_earnings_gates_pass(days: int) -> None:
    decision = _rank(
        direction="neutral",
        composite=80.0,
        tech=70.0,
        rsi=50.0,
        iv=0.40,
        hv=0.25,
        ivr=60.0,
        vol_signal="sell_premium",
        catalyst_active=True,
        apex_input=_gamma_input(catalyst_days=days),
    )
    assert decision.best_match == GAMMA_TRAMPOLINE_NAME
    eligible = [row for row in decision.candidates if row.eligible]
    assert eligible[0].name == GAMMA_TRAMPOLINE_NAME


def test_same_four_legs_without_gates_are_a_double_calendar() -> None:
    decision = _rank(
        direction="neutral",
        catalyst_active=True,
        apex_input=_gamma_input(earnings_date_confirmed=False),
        back_month=False,
    )
    assert decision.best_match != GAMMA_TRAMPOLINE_NAME
    held = next(row for row in decision.candidates if row.name == GAMMA_TRAMPOLINE_NAME)
    assert held.eligible is False
    assert any("Earnings date is missing." in note for note in held.gate_notes)


def test_gamma_card_text_and_max_loss_before_the_scenarios() -> None:
    front_rows, back_rows, _expected = _priced_chain()
    layer = build_strategy_layer(
        strategy_name=GAMMA_TRAMPOLINE_NAME,
        composite=88.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={"contracts": front_rows, "expiry": FRONT, "spot": 100.0},
        vol_layer={"hv": 0.28, "iv": 0.55},
        sentiment_layer={},
        fundamentals_layer={},
        tech_score=60.0,
        ticker="AAPL",
        back_month_contracts=back_rows,
        back_expiry=BACK,
    )
    metrics = layer["metrics"]
    assert metrics.get("scenario_conflict") is None
    assert metrics["max_loss"] == pytest.approx(abs(float(metrics["net_debit_credit"])) * 100, abs=0.01)
    text = f"{layer['what_is_this']} {layer['why_it_fits']} {layer['how_to_execute']}"
    for sentence in (GAMMA_SUMMARY, GAMMA_PROBLEM, GAMMA_GREEKS, GAMMA_SCENARIOS, GAMMA_HOW):
        assert sentence in text


class _ComboAdapter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            name=symbol,
            price=1.0,
            source="test",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    async def submit_order(self, **kwargs: object) -> dict:
        self.payloads.append(dict(kwargs))
        return {"status": "filled", "filled_avg_price": kwargs.get("limit_price") or 1.0}


def _user() -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode="paper_funded",
        cash_balance=100_000.0,
        buying_power=100_000.0,
        portfolio_value=100_000.0,
        starting_balance=100_000.0,
    )


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_gamma_four_legs_execute_as_one_combo(db: AsyncSession) -> None:
    front_rows, back_rows, _expected = _priced_chain()
    metrics = build_registry_metrics(
        "apex_strategy",
        spot=100.0,
        contracts=front_rows,
        back_month_contracts=back_rows,
        front_expiry=FRONT,
        back_expiry=BACK,
        iv=0.55,
        hv=0.28,
        ticker="AAPL",
    )
    assert metrics is not None and len(metrics["legs"]) == 4
    ticket = [
        {
            "symbol": leg["symbol"],
            "side": leg["action"],
            "option_side": leg["side"],
            "price": leg["mid"],
        }
        for leg in metrics["legs"]
    ]
    user = _user()
    db.add(user)
    await db.commit()
    adapter = _ComboAdapter()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=ticket,
        contracts_per_leg=1,
    )
    assert len(orders) == 1
    assert len(adapter.payloads) == 1
    assert adapter.payloads[0]["order_class"] == "mleg"
    assert len(adapter.payloads[0]["legs"]) == 4
