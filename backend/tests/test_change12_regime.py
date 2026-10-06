"""Change 12 strategy regime: IV versus HV, vega, event span, DTE, sentiment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analysis.gate_config import assess_vol_regime
from app.services.evidence_ledger import get, reset_ledger
from app.services.strategy_engine import build_strategy_layer, dte_window_for, strategy_decision

TODAY = datetime.now(timezone.utc).date()


def _put(expiry: str, *, iv: float = 0.30, strike: float = 95.0) -> dict:
    return {
        "symbol": f"AMD{expiry.replace('-', '')[2:]}P00095000",
        "side": "put",
        "strike": strike,
        "expiry": expiry,
        "delta": -0.30,
        "theta": -0.04,
        "iv": iv,
        "bid": 1.20,
        "ask": 1.40,
        "multiplier": 100,
    }


def test_aapl_iv_30_31_versus_hv_20_38_is_rich() -> None:
    view = assess_vol_regime(iv=0.3031, hv=0.2038, iv_rank=43.2)
    assert view.short == "sell premium"
    assert view.display == "IV much above HV"
    assert view.display != "fair"
    assert view.iv_minus_hv_pts == 9.93
    assert view.iv_to_hv == 1.49
    assert view.tie_break is False
    assert "IV much above HV" in view.verdict
    assert "30.31%" in view.verdict
    assert "20.38%" in view.verdict
    assert "IV versus HV is primary" in view.rule
    layer = build_strategy_layer(
        strategy_name="Long Put",
        composite=59.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 260.0,
            "expiry": "2026-10-30",
            "recommendedContract": {"strike": 250.0, "side": "put", "expiry": "2026-10-30", "iv": 0.3031},
            "contracts": [_put("2026-10-30", iv=0.3031, strike=250.0)],
        },
        vol_layer={"iv": 0.3031, "atm_iv": 0.3031, "hv": 0.2038, "iv_rank": 43.2},
        sentiment_layer={"bias": "bearish", "score_0_100": 40},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="AAPL",
    )
    assert layer["vol_regime"] == "IV much above HV"
    assert layer["vol_regime"] != "fair"
    text = layer["why_it_fits"]
    assert "30.31%" in text
    assert "20.38%" in text
    assert text.count("30.31%") == 1
    assert text.count("20.38%") == 1
    assert "IV much above HV" in text
    assert "IV rank 43.2" in text
    assert text.count("IV versus HV is primary") <= 1


def test_near_band_stays_fair() -> None:
    view = assess_vol_regime(iv=0.27, hv=0.225, iv_rank=46.05037606326132)
    assert view.display == "fair"
    assert view.short == "fair"
    assert "IV near HV" in view.verdict


def test_long_leg_spans_earnings_penalty() -> None:
    short_exp = (TODAY + timedelta(days=7)).isoformat()
    long_exp = (TODAY + timedelta(days=35)).isoformat()
    earnings = (TODAY + timedelta(days=14)).isoformat()
    short = _put(short_exp, iv=0.22, strike=90.0)
    long = _put(long_exp, iv=0.40, strike=95.0)
    short["symbol"] = "MSFT261016P00090000"
    long["symbol"] = "MSFT261120P00095000"
    layer = build_strategy_layer(
        strategy_name="Diagonal Spread (bearish)",
        composite=60.0,
        direction="bearish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "MSFT",
            "spot": 100.0,
            "expiry": short_exp,
            "recommendedContract": {"strike": 95.0, "side": "put", "expiry": short_exp, "iv": 0.22},
            "contracts": [short],
        },
        vol_layer={"iv": 0.30, "atm_iv": 0.30, "hv": 0.20, "iv_rank": 60},
        sentiment_layer={"bias": "bearish", "score_0_100": 40},
        fundamentals_layer={
            "score": 55,
            "earnings_calendar": {"next_date": earnings, "date_status": "estimated", "display": f"{earnings} est."},
        },
        tech_score=60.0,
        ticker="MSFT",
        back_month_contracts=[long],
        back_expiry=long_exp,
    )
    text = layer["why_it_fits"]
    assert "Event-vega penalty" in text
    assert long_exp in text
    assert earnings in text
    assert "long put" in text
    assert "spans earnings" in text
    assert "vol points over normal IV" in text


def test_amd_zero_dte_does_not_silently_pass_30_45() -> None:
    today = TODAY.isoformat()
    compliant = (TODAY + timedelta(days=40)).isoformat()
    layer = build_strategy_layer(
        strategy_name="Married Put",
        composite=60.0,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AMD",
            "spot": 100.0,
            "expiry": today,
            "shares_held": 100,
            "expiration_dates": [today, (TODAY + timedelta(days=10)).isoformat(), compliant],
            "recommendedContract": {"strike": 95.0, "side": "put", "expiry": today, "iv": 0.25},
            "contracts": [_put(today, iv=0.25)],
        },
        vol_layer={"iv": 0.25, "atm_iv": 0.25, "hv": 0.25, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="AMD",
    )
    text = layer["why_it_fits"]
    assert "DTE penalty" in text
    assert "0 DTE" in text
    assert "30 to 45 DTE" in text
    assert compliant in text
    assert "Nearest compliant expiry" in text
    assert layer.get("structure_label") == "Protective Put"


def test_bullish_sentiment_on_a_bearish_structure_names_the_conflict() -> None:
    layer = build_strategy_layer(
        strategy_name="Bear Put Spread",
        composite=62.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "JPM",
            "spot": 100.0,
            "expiry": "2026-11-20",
            "recommendedContract": {"strike": 100.0, "side": "put", "expiry": "2026-11-20"},
            "contracts": [
                _put("2026-11-20", iv=0.25, strike=100.0),
                _put("2026-11-20", iv=0.25, strike=90.0),
            ],
        },
        vol_layer={"iv": 0.25, "atm_iv": 0.25, "hv": 0.25, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 73},
        fundamentals_layer={"score": 55},
        tech_score=55.0,
        ticker="JPM",
    )
    text = layer["why_it_fits"]
    assert "Sentiment conflict" in text
    assert "73" in text
    assert "weight 15%" in text
    assert "bearish" in text
    assert "prevailed" in text or "technical direction" in text
    assert "low conviction" in layer["outlook"]


def test_missing_iv_rank_is_not_a_bare_dash() -> None:
    layer = build_strategy_layer(
        strategy_name="Long Put",
        composite=55.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "VZ",
            "spot": 40.0,
            "expiry": "2026-11-20",
            "recommendedContract": {"strike": 40.0, "side": "put", "expiry": "2026-11-20"},
            "contracts": [_put("2026-11-20", iv=0.22, strike=40.0)],
        },
        vol_layer={
            "iv": 0.22,
            "atm_iv": 0.22,
            "hv": 0.20,
            "iv_rank": None,
            "iv_rank_gap": "IV rank is a data gap: published IV history is missing.",
        },
        sentiment_layer={"bias": "neutral", "score_0_100": 50},
        fundamentals_layer={"score": 50},
        tech_score=50.0,
        ticker="VZ",
    )
    text = layer["why_it_fits"]
    assert "IV rank —" not in text
    assert "IV rank unavailable:" in text
    assert "published IV history is missing" in text


def test_gamma_earnings_window_is_not_an_option_dte_rule() -> None:
    assert dte_window_for("Gamma Trampoline™") is None
    assert dte_window_for("Long Call LEAPS") == (366, None)


def test_rich_iv_hedge_evaluates_a_collar_and_records_the_rank() -> None:
    reset_ledger("AAPL")
    decision = strategy_decision(
        composite=78.0,
        direction="bullish",
        vol_signal="fair",
        rsi=72.0,
        iv=0.3031,
        hv=0.2038,
        ivr=43.2,
        tech_score=70.0,
        sentiment_score=60.0,
        catalyst_days=8,
        symbol="AAPL",
    )
    captured = get("AAPL")
    names = [row.name for row in decision.candidates]
    assert "Collar" in names
    joined = " ".join(decision.risk_notes)
    assert "ranked first" in joined
    assert "short call" in joined.lower() or "Collar scored" in joined
    assert any(getattr(row, "key", None) == "rank" for row in captured)
    assert any(getattr(row, "kind", None) == "gate" for row in captured)
