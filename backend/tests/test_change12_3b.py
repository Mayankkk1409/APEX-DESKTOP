"""Change 12 agent 3B: one IV-versus-HV rule, and the five long-leg earnings names."""

from __future__ import annotations

import inspect

from app.analysis.gate_config import (
    IV_MISMATCH_VOL_POINTS,
    assess_vol_regime,
    gamma_front_back_iv_ratio_min,
    term_structure_inversion,
)
from app.services.evidence_ledger import get, reset_ledger
from app.services.strategy_engine import build_strategy_layer, strategy_decision
from app.services.volatility_intel import _iv_hv_signal, build_analysis_cards, resolve_recommended_contract

# Dates from the QA names whose earnings sit after the short expiry and before the long expiry.
# Long-leg IV and normal IV are inputs. The penalty is their difference in vol points.
LONG_LEG_EARNINGS = (
    ("MSFT", "2026-10-30", "2026-11-04", "2026-11-20", 0.41, 0.23),
    ("TSLA", "2026-10-23", "2026-10-28", "2026-11-20", 0.37, 0.21),
    ("VZ", "2026-10-23", "2026-10-26", "2026-11-20", 0.34, 0.19),
    ("META", "2026-10-30", "2026-11-04", "2026-11-06", 0.46, 0.24),
    ("HD", "2026-11-13", "2026-11-17", "2026-12-18", 0.39, 0.22),
)


def _measured_points(long_iv: float, normal_iv: float) -> float:
    return round((long_iv - normal_iv) * 100.0, 2)


def _rank_index(rows: list, name: str) -> int:
    return next(index for index, row in enumerate(rows) if row.name == name)


def _card(iv: float, hv: float, *, iv_rank: float = 43.2) -> dict:
    return build_strategy_layer(
        strategy_name="Long Put",
        composite=59.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 260.0,
            "expiry": "2026-10-30",
            "contracts": [
                {
                    "symbol": "AAPL261030P00255000",
                    "side": "put",
                    "strike": 255.0,
                    "expiry": "2026-10-30",
                    "delta": -0.45,
                    "bid": 4.0,
                    "ask": 4.2,
                    "iv": iv,
                }
            ],
        },
        vol_layer={"iv": iv, "atm_iv": iv, "hv": hv, "iv_rank": iv_rank, "feed": "indicative"},
        sentiment_layer={"bias": "bearish", "score_0_100": 40},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="AAPL",
    )


def _decision(ticker: str, span: dict | None):
    reset_ledger(ticker)
    return strategy_decision(
        composite=60.0,
        direction="bullish",
        vol_signal="fair",
        rsi=50.0,
        iv=0.25,
        hv=0.22,
        ivr=40.0,
        tech_score=70.0,
        sentiment_score=50.0,
        catalyst_active=False,
        back_month_available=True,
        symbol=ticker,
        event_span=span,
    )


def test_one_rule_is_five_points_and_inversion_is_one_point_two_five() -> None:
    assert IV_MISMATCH_VOL_POINTS == 5.0
    assert gamma_front_back_iv_ratio_min() == 1.25
    assert term_structure_inversion(1.25, 1.0) is True
    assert term_structure_inversion(1.249, 1.0) is False
    assert "iv_hv_rich_pts" not in inspect.getsource(resolve_recommended_contract)
    rule = assess_vol_regime(iv=0.30, hv=0.20, iv_rank=40.0).rule
    assert "10" not in rule
    assert "5" in rule


def test_aapl_3031_versus_2038_is_rich_on_the_layer_and_the_card() -> None:
    layer = _iv_hv_signal(0.3031, 0.2038)
    assert layer["signal"] == "sell_premium"
    assert layer["gap_pts"] == 9.93
    assert "between_bands" not in layer["signal"]
    view = assess_vol_regime(iv=0.3031, hv=0.2038, iv_rank=43.2)
    assert view.short == "sell premium"
    assert view.display == "IV much above HV"
    assert view.tie_break is False
    cards = build_analysis_cards(
        {
            "atm_iv": 0.3031,
            "hv": 0.2038,
            "hv_by_window": {"30D": 0.2038},
            "iv_vs_hv": layer,
            "dte": 25,
            "expiry": "2026-10-30",
        }
    )
    body = next(card["body"] for card in cards if card["id"] == "iv_rv_spread")
    assert "more than 5 vol points" in body
    assert "10 vol" not in body
    assert "30.3%" in body or "9.9" in body
    card = _card(0.3031, 0.2038)
    assert card["vol_regime"] == "IV much above HV"
    assert card["vol_regime"] != "fair"
    assert "30.31%" in card["why_it_fits"]
    assert "20.38%" in card["why_it_fits"]
    assert "rich" in card["why_it_fits"]


def test_exact_five_point_boundaries_stay_tight() -> None:
    fair_rich = assess_vol_regime(iv=0.25, hv=0.20, iv_rank=43.2)
    rich = assess_vol_regime(iv=0.2501, hv=0.20, iv_rank=43.2)
    fair_cheap = assess_vol_regime(iv=0.20, hv=0.25, iv_rank=43.2)
    cheap = assess_vol_regime(iv=0.1999, hv=0.25, iv_rank=43.2)
    assert fair_rich.iv_minus_hv_pts == 5.0
    assert fair_rich.short == "fair"
    assert fair_rich.display == "fair"
    assert _iv_hv_signal(0.25, 0.20)["signal"] == "fair"
    assert rich.iv_minus_hv_pts == 5.01
    assert rich.short == "sell premium"
    assert rich.display == "IV much above HV"
    assert _iv_hv_signal(0.2501, 0.20)["signal"] == "sell_premium"
    assert fair_cheap.iv_minus_hv_pts == -5.0
    assert fair_cheap.short == "fair"
    assert _iv_hv_signal(0.20, 0.25)["signal"] == "fair"
    assert cheap.iv_minus_hv_pts == -5.01
    assert cheap.short == "buy premium"
    assert cheap.display == "IV much below HV"
    assert _iv_hv_signal(0.1999, 0.25)["signal"] == "buy_premium"
    assert _card(0.25, 0.20)["vol_regime"] == "fair"
    assert _card(0.2501, 0.20)["vol_regime"] == "IV much above HV"
    assert _card(0.1999, 0.25)["vol_regime"] == "IV much below HV"
    near = assess_vol_regime(iv=0.25, hv=0.24, iv_rank=62.0)
    assert near.tie_break is True
    assert near.short == "sell premium"


def test_five_names_rank_lower_with_the_measured_penalty_in_the_breakdown() -> None:
    for ticker, short_exp, earnings, long_exp, long_iv, normal_iv in LONG_LEG_EARNINGS:
        plain = _decision(ticker, None)
        span = {
            "earnings_date": earnings,
            "short_expiry": short_exp,
            "long_expiry": long_exp,
            "normal_iv": normal_iv,
            "spot": 100.0,
            "contracts": [
                {"side": "call", "strike": 100.0, "expiry": long_exp, "iv": long_iv},
            ],
        }
        ranked = _decision(ticker, span)
        measured = _measured_points(long_iv, normal_iv)
        assert measured > 5.0, ticker
        plain_row = next(row for row in plain.candidates if row.name == "Diagonal Spread (bullish)")
        row = next(item for item in ranked.candidates if item.name == "Diagonal Spread (bullish)")
        plain_top = max(item.score for item in plain.candidates if item.eligible)
        ranked_top = max(item.score for item in ranked.candidates if item.eligible)
        assert plain_row.score == plain_top, ticker
        assert row.score == round(plain_row.score - measured, 1), ticker
        assert row.score < ranked_top, ticker
        assert _rank_index(ranked.candidates, row.name) >= _rank_index(plain.candidates, plain_row.name), ticker
        penalty = next(item for item in row.score_breakdown if item["label"] == "Event-vega penalty")
        assert penalty["value"] == measured, ticker
        assert penalty["score_before"] == plain_row.score
        assert penalty["score_after"] == row.score
        assert earnings in penalty["note"]
        assert long_exp in penalty["note"]
        assert f"{measured:.2f}" in penalty["note"]
        hedge = next(item for item in ranked.candidates if item.name == "Married Put")
        assert not any(item["label"] == "Event-vega penalty" for item in hedge.score_breakdown)
        api = ranked.to_api_dict()
        api_row = next(item for item in api["candidates"] if item["name"] == row.name)
        assert api_row["score_breakdown"][0]["value"] == measured
        ledger = get(ticker)
        score_row = next(entry for entry in ledger if entry.key == f"{row.name}:score")
        assert score_row.inputs["breakdown"][0]["value"] == measured
        penalty_row = next(entry for entry in ledger if entry.key == f"{row.name}:event_vega_penalty")
        assert penalty_row.inputs["points"] == measured
        assert penalty_row.inputs["breakdown"][0]["value"] == measured
        assert penalty_row.value is not None
        assert f"{measured:.2f}" in str(penalty_row.value)


def test_unmeasured_long_leg_premium_is_not_invented() -> None:
    ticker, short_exp, earnings, long_exp, _long_iv, _normal = LONG_LEG_EARNINGS[0]
    plain = _decision(ticker, None)
    ranked = _decision(
        ticker,
        {
            "earnings_date": earnings,
            "short_expiry": short_exp,
            "long_expiry": long_exp,
            "spot": 100.0,
            "contracts": [{"side": "call", "strike": 100.0, "expiry": long_exp}],
        },
    )
    plain_row = next(row for row in plain.candidates if row.name == "Diagonal Spread (bullish)")
    row = next(item for item in ranked.candidates if item.name == "Diagonal Spread (bullish)")
    assert row.score == plain_row.score
    penalty = next(item for item in row.score_breakdown if item["label"] == "Event-vega penalty")
    assert penalty["value"] is None
    assert "score_after" not in penalty
    assert "could not be measured" in penalty["note"]
    assert "Penalty" not in penalty["note"]
    ledger = next(entry for entry in get(ticker) if entry.key == f"{row.name}:event_vega_penalty")
    assert ledger.inputs["points"] is None
