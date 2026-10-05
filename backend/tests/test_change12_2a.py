"""Change 12 strategy-logic cases: regime, event vega, DTE, and sentiment."""

from __future__ import annotations

from app.analysis.gate_config import assess_vol_regime, classify_vol_regime
from app.contracts import ledger
from app.services.strategy_engine import build_strategy_layer, strategy_decision


def test_aapl_3031_vs_2038_is_rich_not_fair() -> None:
    view = assess_vol_regime(iv=0.3031, hv=0.2038, iv_rank=43.2)
    assert view.iv_minus_hv_pts == 9.93
    assert view.short == "sell premium"
    assert view.short != "fair"
    assert "rich" in view.verdict
    assert "IV much above HV" in view.verdict
    assert "30.31%" in view.verdict
    assert "20.38%" in view.verdict
    assert "9.93" in view.verdict
    assert "1.49x" in view.verdict
    assert "IV rank 43.2" in view.verdict
    assert "Rule:" in view.verdict
    assert classify_vol_regime(iv_rank=43.2, iv=0.3031, hv=0.2038) == "sell premium"
    layer = build_strategy_layer(
        strategy_name="Long Put",
        composite=59.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 260.0,
            "expiry": "2026-10-30",
            "recommendedContract": {"strike": 255.0, "side": "put", "expiry": "2026-10-30"},
            "contracts": [
                {
                    "symbol": "AAPL261030P00255000",
                    "side": "put",
                    "strike": 255.0,
                    "expiry": "2026-10-30",
                    "delta": -0.45,
                    "bid": 4.0,
                    "ask": 4.2,
                    "iv": 0.3031,
                }
            ],
        },
        vol_layer={"iv": 0.3031, "atm_iv": 0.3031, "hv": 0.2038, "iv_rank": 43.2},
        sentiment_layer={"bias": "bullish", "score_0_100": 55},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        ticker="AAPL",
    )
    assert layer["vol_regime"] == "IV much above HV"
    assert layer["vol_regime"] != "fair"
    text = layer["why_it_fits"]
    assert "30.31%" in text
    assert "20.38%" in text
    assert "IV much above HV" in text
    assert "rich" in text
    assert "IV rank 43.2" in text


def test_near_band_stays_fair_when_iv_rank_does_not_disagree() -> None:
    view = assess_vol_regime(iv=0.27, hv=0.225, iv_rank=46.05)
    assert view.short == "fair"
    assert "IV near HV" in view.verdict


def test_iv_rank_tie_break_when_the_primary_band_is_near() -> None:
    view = assess_vol_regime(iv=0.25, hv=0.24, iv_rank=62.0)
    assert view.short == "sell premium"
    assert view.tie_break is True
    assert "breaks the tie" in view.verdict


def test_missing_iv_rank_is_not_a_bare_dash() -> None:
    layer = build_strategy_layer(
        strategy_name="Bull Call Spread",
        composite=60.0,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "MSFT",
            "spot": 400.0,
            "expiry": "2026-11-20",
            "contracts": [
                {"symbol": "MSFT1", "side": "call", "strike": 400.0, "expiry": "2026-11-20", "bid": 5.0, "ask": 5.2},
                {"symbol": "MSFT2", "side": "call", "strike": 420.0, "expiry": "2026-11-20", "bid": 2.0, "ask": 2.1},
            ],
        },
        vol_layer={"iv": 0.22, "hv": 0.21, "iv_rank": None, "iv_rank_gap": "published IV history is missing"},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 50},
        tech_score=70.0,
        ticker="MSFT",
    )
    text = layer["why_it_fits"]
    assert "IV rank —" not in text
    assert "IV rank unavailable" in text or "published IV history is missing" in text


def test_long_leg_spans_earnings_names_the_leg_and_date() -> None:
    cases = [
        ("MSFT", "2026-10-30", "2026-11-04", "2026-11-20"),
        ("TSLA", "2026-10-23", "2026-10-28", "2026-11-20"),
        ("VZ", "2026-10-23", "2026-10-26", "2026-11-20"),
        ("META", "2026-10-30", "2026-11-04", "2026-11-06"),
        ("HD", "2026-11-13", "2026-11-17", "2026-12-18"),
    ]
    for ticker, short_exp, earnings, long_exp in cases:
        layer = build_strategy_layer(
            strategy_name="Diagonal Spread (bullish)",
            composite=60.0,
            direction="bullish",
            vol_signal="sell_premium",
            chain_analysis={
                "symbol": ticker,
                "spot": 100.0,
                "expiry": short_exp,
                "contracts": [
                    {
                        "symbol": f"{ticker}S",
                        "side": "call",
                        "strike": 110.0,
                        "expiry": short_exp,
                        "bid": 1.0,
                        "ask": 1.1,
                        "iv": 0.28,
                        "delta": 0.30,
                    }
                ],
            },
            back_month_contracts=[
                {
                    "symbol": f"{ticker}L",
                    "side": "call",
                    "strike": 100.0,
                    "expiry": long_exp,
                    "bid": 4.0,
                    "ask": 4.2,
                    "iv": 0.40,
                    "delta": 0.55,
                }
            ],
            back_expiry=long_exp,
            vol_layer={"iv": 0.40, "atm_iv": 0.32, "hv": 0.22, "iv_rank": 60},
            sentiment_layer={"bias": "bullish", "score_0_100": 60},
            fundamentals_layer={
                "score": 50,
                "earnings_calendar": {"next_date": earnings, "date_status": "estimated", "display": f"{earnings} est."},
            },
            tech_score=70.0,
            ticker=ticker,
        )
        text = layer["why_it_fits"]
        assert "Event-vega penalty" in text, ticker
        assert earnings in text, ticker
        assert "long call" in text, ticker
        assert long_exp in text, ticker
        assert "vol points" in text, ticker


def test_amd_zero_dte_protective_put_states_the_30_to_45_window() -> None:
    layer = build_strategy_layer(
        strategy_name="Married Put",
        composite=55.0,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AMD",
            "spot": 160.0,
            "expiry": "2026-10-05",
            "shares_held": 200,
            "recommendedContract": {"strike": 155.0, "side": "put", "expiry": "2026-10-05"},
            "contracts": [
                {
                    "symbol": "AMD261005P00155000",
                    "side": "put",
                    "strike": 155.0,
                    "expiry": "2026-10-05",
                    "bid": 1.2,
                    "ask": 1.3,
                    "delta": -0.30,
                    "iv": 0.40,
                }
            ],
        },
        vol_layer={"iv": 0.40, "hv": 0.35, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 50},
        tech_score=70.0,
        ticker="AMD",
    )
    text = f"{layer['why_it_fits']} {layer['how_to_execute']}"
    put_expiries = [
        str(leg.get("expiry"))
        for leg in layer["metrics"]["legs"]
        if isinstance(leg, dict) and leg.get("side") == "put"
    ]
    assert "30" in text and "45" in text
    if not put_expiries or put_expiries[0][:10] == "2026-10-05":
        assert "DTE penalty" in text
        assert "outside" in text
    else:
        assert "The candidate uses" in text


def test_bullish_sentiment_bearish_structure_names_the_conflict() -> None:
    layer = build_strategy_layer(
        strategy_name="Bear Call Spread (credit)",
        composite=62.0,
        direction="bearish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "JPM",
            "spot": 300.0,
            "expiry": "2026-11-20",
            "contracts": [
                {
                    "symbol": "JPM1",
                    "side": "call",
                    "strike": 310.0,
                    "expiry": "2026-11-20",
                    "bid": 2.0,
                    "ask": 2.1,
                    "delta": 0.20,
                },
                {
                    "symbol": "JPM2",
                    "side": "call",
                    "strike": 320.0,
                    "expiry": "2026-11-20",
                    "bid": 1.0,
                    "ask": 1.05,
                    "delta": 0.12,
                },
            ],
        },
        vol_layer={"iv": 0.30, "hv": 0.22, "iv_rank": 55},
        sentiment_layer={"bias": "bullish", "score_0_100": 73},
        fundamentals_layer={"score": 50},
        tech_score=52.0,
        ticker="JPM",
    )
    text = layer["why_it_fits"]
    assert "Sentiment conflict" in text
    assert "73" in text
    assert "15%" in text
    assert "30%" in text
    assert "bearish" in text
    assert "prevailed" in text or "technical direction" in text
    assert "low conviction" in text
    assert "low conviction" in layer["outlook"]


def test_long_vega_penalty_is_waived_when_the_term_structure_is_inverted() -> None:
    plain = strategy_decision(
        composite=70.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=70.0,
        iv=0.40,
        hv=0.22,
        ivr=40.0,
        tech_score=70.0,
        back_month_available=True,
        symbol="AMD",
    )
    diagonal = next(row for row in plain.candidates if row.name == "Diagonal Spread (bullish)")
    assert any("Long-vega penalty" in note for note in diagonal.gate_notes)
    waived = strategy_decision(
        composite=70.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=70.0,
        iv=0.40,
        hv=0.22,
        ivr=40.0,
        tech_score=70.0,
        back_month_available=True,
        symbol="AMD",
        apex_input=__import__("app.services.apex_strategy", fromlist=["ApexStrategyInput"]).ApexStrategyInput(
            front_iv=0.50,
            back_iv=0.30,
            term_structure_inverted=True,
        ),
    )
    waived_row = next(row for row in waived.candidates if row.name == "Diagonal Spread (bullish)")
    assert any("inversion justifies" in note.lower() for note in waived_row.gate_notes)
    assert not any(note.startswith("Long-vega penalty") for note in waived_row.gate_notes)


def test_rich_iv_hedge_records_why_the_winner_beat_the_collar() -> None:
    decision = strategy_decision(
        composite=70.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=55.0,
        iv=0.40,
        hv=0.22,
        ivr=55.0,
        tech_score=70.0,
        symbol="AAPL",
        catalyst_days=12,
        earnings_date_confirmed=True,
    )
    text = " ".join(decision.risk_notes)
    assert "Collar" in text
    assert "ranked first" in text
    assert "short call" in text


def test_ledger_record_is_called_for_gates_and_scores(monkeypatch) -> None:
    calls = []

    def _capture(entry) -> None:
        calls.append(entry)

    monkeypatch.setattr(ledger, "record", _capture)
    strategy_decision(
        composite=70.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.22,
        tech_score=70.0,
        symbol="AAPL",
    )
    kinds = {entry.kind for entry in calls}
    assert "gate" in kinds
    assert "candidate" in kinds
    assert "score" in kinds
