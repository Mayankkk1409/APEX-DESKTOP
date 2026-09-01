"""Strategy engine — layer order helpers and payoff metrics."""

from __future__ import annotations

from app.analysis.layers import DEEP_SCAN_LAYERS, SCAN_SLIDE_LAYERS, DeepScanLayer
from app.services.options_analysis import strategy_selection_bucket as bucket_from_options
from app.services.strategy_engine import (
    build_apex_score_layer,
    build_strategy_layer,
    compute_strategy_metrics,
    select_strategy,
)

CONTRACTS = [
    {"side": "call", "strike": 100.0, "bid": 3.8, "ask": 4.0, "symbol": "XYZ260701C00100000", "expiry": "2026-07-01"},
    {"side": "call", "strike": 105.0, "bid": 1.8, "ask": 2.0, "symbol": "XYZ260701C00105000", "expiry": "2026-07-01"},
    {"side": "call", "strike": 110.0, "bid": 0.8, "ask": 1.0, "symbol": "XYZ260701C00110000", "expiry": "2026-07-01"},
    {"side": "put", "strike": 95.0, "bid": 0.7, "ask": 0.9, "symbol": "XYZ260701P00095000", "expiry": "2026-07-01"},
    {"side": "put", "strike": 100.0, "bid": 1.9, "ask": 2.1, "symbol": "XYZ260701P00100000", "expiry": "2026-07-01"},
    {"side": "put", "strike": 105.0, "bid": 3.8, "ask": 4.0, "symbol": "XYZ260701P00105000", "expiry": "2026-07-01"},
]


def test_scan_slide_layer_order_in_enum() -> None:
    values = [layer.value for layer in DEEP_SCAN_LAYERS]
    assert values.index("sentiment") < values.index("fundamentals")
    assert values.index("fundamentals") < values.index("apex_score")
    assert values.index("apex_score") < values.index("strategy")
    assert values.index("strategy") < values.index("risk_review")


def test_scan_slide_layers_match_user_facing_carousel() -> None:
    assert SCAN_SLIDE_LAYERS == (
        "technical",
        "options_chain_greeks",
        "volatility",
        "sentiment",
        "fundamentals",
        "apex_score",
        "strategy",
        "risk_review",
    )
    assert SCAN_SLIDE_LAYERS.index("fundamentals") < SCAN_SLIDE_LAYERS.index("apex_score")
    assert SCAN_SLIDE_LAYERS.index("apex_score") < SCAN_SLIDE_LAYERS.index("strategy")
    assert SCAN_SLIDE_LAYERS.index("strategy") < SCAN_SLIDE_LAYERS.index("risk_review")


def test_select_strategy_no_trade_on_low_composite() -> None:
    label = select_strategy(
        composite=45.0,
        direction="neutral",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.30,
        hv=0.28,
        ivr=60.0,
        tech_score=70.0,
    )
    assert label == "NO TRADE — Insufficient Conviction"


def test_select_strategy_shows_playbook_in_manual_band() -> None:
    label = select_strategy(
        composite=55.0,
        direction="neutral",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.30,
        hv=0.28,
        ivr=60.0,
        tech_score=70.0,
    )
    assert label != "NO TRADE — Insufficient Conviction"


def test_select_strategy_apex_strategy_on_catalyst() -> None:
    from app.analysis.layers import APEX_STRATEGY_NAME
    from app.services.apex_strategy import ApexStrategyInput

    apex_input = ApexStrategyInput(
        catalyst_days=7,
        term_structure_inverted=True,
        front_iv=0.45,
        back_iv=0.35,
        front_ivr=75.0,
        four_leg_structure=True,
        legs_same_strikes=True,
        call_delta=0.20,
        put_delta=0.20,
        front_premium_offset_pct=0.55,
        adv=5_000_000,
        open_interest=2000,
        spread_pct=5.0,
    )
    label = select_strategy(
        composite=78.0,
        direction="neutral",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.38,
        hv=0.30,
        ivr=75.0,
        tech_score=75.0,
        catalyst_active=True,
        confirmed_pattern_count=1,
        apex_input=apex_input,
    )
    assert label == APEX_STRATEGY_NAME


def test_bull_call_spread_metrics() -> None:
    metrics = compute_strategy_metrics(
        "Bull Call Spread",
        spot=100.0,
        contracts=CONTRACTS,
        recommended={"strike": 100.0, "side": "call", "expiry": "2026-07-01"},
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["net_type"] == "debit"
    assert metrics["net_debit_credit"] is not None
    assert metrics["max_loss"] is not None
    assert metrics["max_profit"] is not None
    assert len(metrics["breakevens"]) == 1
    assert len(metrics["legs"]) == 2


def test_iron_condor_metrics_credit() -> None:
    metrics = compute_strategy_metrics(
        "Short Iron Condor",
        spot=100.0,
        contracts=CONTRACTS,
        recommended=None,
        front_expiry="2026-07-01",
        ticker="XYZ",
    )
    assert metrics["net_type"] in {"credit", "debit"}
    assert len(metrics["legs"]) >= 2
    assert metrics["max_profit"] is not None or metrics["net_debit_credit"] is not None


def test_strategy_selection_bucket_new_playbook_labels() -> None:
    assert bucket_from_options("APEX Benchmark Greeks Strategy", "bullish") == ("buy", "call")
    assert bucket_from_options("Married Put", "bullish") == ("buy", "put")
    assert bucket_from_options("Bull Put Spread (credit)", "bullish") == ("sell", "put")


def test_apex_score_layer_key_exists() -> None:
    assert DeepScanLayer.APEX_SCORE.value == "apex_score"


def test_build_apex_score_layer_has_six_sections() -> None:
    layer = build_apex_score_layer(
        composite=78.0,
        tech_score=82.0,
        vol_score=72.0,
        greek_score=70.0,
        sentiment_score=65.0,
        fund_score=60.0,
        risk_score=74.0,
        technical_narrative="EMA stack aligned bullish.",
        chain_analysis={
            "execution_tier": "auto_exec",
            "summary": {
                "contract_count": 4,
                "verdict_counts": {"tradeable": 2, "buy_candidate": 1, "sell_candidate": 0},
                "vega_cap_blocked": [],
                "gate_failures": {"spread": 0},
            },
        },
        vol_layer={
            "iv": 0.35,
            "hv": 0.28,
            "iv_rank": 55,
            "signal": "sell_premium",
            "narrative": "IV rich versus HV on selected expiry.",
        },
        sentiment_layer={"score_0_100": 65, "bias": "bullish", "narrative": "Flow positive."},
        fundamentals_layer={"score": 60, "name": "Test Co"},
        direction="bullish",
        technical_context={
            "last": 150.0,
            "rsi": 55.0,
            "macd": {"histogram": 0.12},
            "ema": {200: 145.0},
            "supertrend": {"direction": "bullish", "value": 148.0},
            "ema_aligned_bullish": True,
        },
    )
    assert layer["composite_score"] == 78.0
    assert layer["clears_threshold"] is True
    assert len(layer["sections"]) == 6
    assert {s["id"] for s in layer["sections"]} == {
        "technicals",
        "options",
        "volatility",
        "sentiment",
        "fundamentals",
        "risk",
    }
    assert layer.get("paragraphs")
    assert len(layer["paragraphs"]) >= 2
    assert layer.get("interpretation")
    for section in layer["sections"]:
        assert section.get("narrative")
        assert len(section["narrative"]) > 80
        assert section.get("paragraphs")
        assert len(section["paragraphs"]) >= 3
        assert section.get("interpretation")
        assert section.get("breakdown")
        for row in section["breakdown"]:
            assert "label" in row
            assert "value" in row
            assert "note" in row


def test_build_apex_score_layer_narrative_uses_layer_data() -> None:
    layer = build_apex_score_layer(
        composite=55.0,
        tech_score=58.0,
        vol_score=55.0,
        greek_score=45.0,
        sentiment_score=50.0,
        fund_score=52.0,
        risk_score=40.0,
        technical_narrative="Mixed EMA structure.",
        chain_analysis={
            "execution_tier": "caution",
            "summary": {
                "contract_count": 6,
                "verdict_counts": {"rejected": 3},
                "gate_failures": {"spread": 2},
                "vega_cap_blocked": ["SYM1"],
            },
        },
        vol_layer={"iv": 0.22, "hv": 0.30, "signal": "buy_premium", "expected_move": {"percent": 4.2}},
        sentiment_layer={"score": -10, "score_0_100": 45, "bias": "bearish"},
        fundamentals_layer={
            "score": 52,
            "revenue": {"yoy_pct": 3.5},
            "eps_trend": {"trend": "flat", "consecutive_beats": 0},
        },
        direction="neutral",
    )
    assert layer["clears_threshold"] is False
    tech = next(s for s in layer["sections"] if s["id"] == "technicals")
    assert "Mixed EMA structure" in tech["narrative"]
    vol = next(s for s in layer["sections"] if s["id"] == "volatility")
    assert "buy_premium" in vol["narrative"]
    risk = next(s for s in layer["sections"] if s["id"] == "risk")
    assert "caution" in risk["narrative"]


def test_build_strategy_layer_blocked_tier() -> None:
    layer = build_strategy_layer(
        strategy_name="Bull Call Spread",
        composite=48.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={"spot": 100.0, "recommendedContract": None, "contracts": CONTRACTS},
        vol_layer={"iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 45},
        fundamentals_layer={"score": 50},
        tech_score=52.0,
    )
    assert layer["tradeable"] is False
    assert layer["execution_tier"] == "blocked"
    assert "Not tradeable" in layer["selected_strategy"]
    assert layer["metrics"]["legs"] == []


def test_build_strategy_layer_includes_playbook_and_metrics() -> None:
    layer = build_strategy_layer(
        strategy_name="Bull Call Spread",
        composite=80.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={
            "symbol": "XYZ",
            "spot": 100.0,
            "expiry": "2026-07-01",
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-07-01"},
            "contracts": CONTRACTS,
        },
        vol_layer={"iv_rank": 40, "iv": 0.25},
        sentiment_layer={"bias": "bullish", "score_0_100": 68},
        fundamentals_layer={"score": 62},
        tech_score=84.0,
        ticker="XYZ",
    )
    assert layer["selected_strategy"] == "Bull Call Spread"
    assert layer["what_is_this"]
    assert layer["why_recommended"]
    assert layer["how_to_execute"]
    assert layer["metrics"]["net_type"] == "debit"
    assert layer["metrics"]["max_loss"] is not None
    assert layer["metrics"]["breakevens"]


def test_calendar_spread_metrics_use_dedicated_payoff() -> None:
    front = [
        {"side": "call", "strike": 100.0, "bid": 2.8, "ask": 3.0, "expiry": "2026-08-01", "symbol": "AAPL260801C00100000"},
    ]
    back = [
        {"side": "call", "strike": 100.0, "bid": 4.8, "ask": 5.0, "expiry": "2026-09-01", "symbol": "AAPL260901C00100000"},
    ]
    metrics = compute_strategy_metrics(
        "Calendar Spread",
        spot=100.0,
        contracts=front,
        recommended={"strike": 100.0, "side": "call", "expiry": "2026-08-01"},
        back_month_contracts=back,
        front_expiry="2026-08-01",
        back_expiry="2026-09-01",
        iv=0.28,
    )
    assert len(metrics["legs"]) == 2
    assert metrics["net_type"] == "debit"
    assert metrics["max_profit"] is not None
    assert metrics["max_loss"] is not None
    assert len(metrics["breakevens"]) >= 1
    assert metrics.get("max_profit_iv_assumption_dependent") is True


def test_build_strategy_layer_blocks_invalid_calendar() -> None:
    layer = build_strategy_layer(
        strategy_name="Calendar Spread",
        composite=80.0,
        direction="neutral",
        vol_signal="fair",
        chain_analysis={
            "spot": 100.0,
            "symbol": "AAPL",
            "expiry": "2026-08-01",
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-08-01"},
            "contracts": [
                {"side": "call", "strike": 100.0, "bid": 2.8, "ask": 3.0, "expiry": "2026-08-01", "symbol": "AAPL260801C00100000"},
            ],
        },
        vol_layer={"iv": 0.28},
        sentiment_layer={},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
    )
    assert layer["tradeable"] is False
    assert layer["validation_errors"]
