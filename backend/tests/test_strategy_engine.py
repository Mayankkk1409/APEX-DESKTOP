"""Strategy engine — layer order helpers and payoff metrics."""

from __future__ import annotations

import pytest

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
    assert label == "Short Iron Condor"
    assert "NO TRADE" not in label


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
        adv=6_000_000,
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
    assert layer["selected_strategy"] == "Bull Call Spread"
    assert layer["metrics"]["legs"]
    assert layer["what_is_this"]
    assert layer["how_to_execute"]


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


_BOTH_ELIGIBLE = dict(
    composite=82.0,
    direction="bullish",
    vol_signal="sell_premium",
    rsi=50.0,
    iv=0.20,
    hv=0.35,
    ivr=40.0,
    tech_score=88.0,
    confirmed_pattern_count=1,
    data_fresh=True,
)


def test_risk_profile_changes_best_match_when_both_structures_eligible() -> None:
    conservative = select_strategy(**_BOTH_ELIGIBLE, risk_profile="conservative")
    aggressive = select_strategy(**_BOTH_ELIGIBLE, risk_profile="aggressive")
    moderate = select_strategy(**_BOTH_ELIGIBLE, risk_profile="moderate")
    custom = select_strategy(**_BOTH_ELIGIBLE, risk_profile="custom")
    assert conservative == "Short Iron Condor"
    assert aggressive == "Bull Call Spread"
    assert conservative != aggressive
    assert moderate == aggressive
    assert custom == moderate


def test_aggressive_promotes_debit_ahead_of_higher_scored_neutral_income() -> None:
    from app.services.strategy_recommendation import StrategyCandidate, order_candidates_for_risk_profile

    ranked = [
        StrategyCandidate("Short Iron Condor", 90.0, "candidate", True),
        StrategyCandidate("Bull Call Spread", 80.0, "candidate", True),
    ]
    assert order_candidates_for_risk_profile(ranked, "moderate")[0].name == "Short Iron Condor"
    assert order_candidates_for_risk_profile(ranked, "aggressive")[0].name == "Bull Call Spread"
    assert order_candidates_for_risk_profile(ranked, "conservative")[0].name == "Short Iron Condor"


def test_custom_honors_structure_limits_when_stored() -> None:
    limited = select_strategy(
        **_BOTH_ELIGIBLE,
        risk_profile="custom",
        structure_limits=frozenset({"Short Iron Condor"}),
    )
    assert limited == "Short Iron Condor"
    assert select_strategy(**_BOTH_ELIGIBLE, risk_profile="custom") == select_strategy(
        **_BOTH_ELIGIBLE, risk_profile="moderate"
    )


@pytest.mark.parametrize("profile", ["conservative", "moderate", "aggressive", "custom"])
def test_failed_composite_gate_is_no_trade_for_every_profile(profile: str) -> None:
    label = select_strategy(
        composite=40.0,
        direction="bullish",
        vol_signal="buy_premium",
        rsi=55.0,
        iv=0.20,
        hv=0.35,
        tech_score=90.0,
        confirmed_pattern_count=2,
        risk_profile=profile,
    )
    assert "NO TRADE" not in label
    assert label in {"Bull Call Spread", "Married Put", "APEX Benchmark Greeks Strategy"}


@pytest.mark.parametrize("profile", ["conservative", "moderate", "aggressive", "custom"])
def test_iv_above_135x_keeps_the_ranked_structure(profile: str) -> None:
    from app.services.strategy_engine import strategy_decision

    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.50,
        hv=0.30,
        tech_score=90.0,
        confirmed_pattern_count=2,
        risk_profile=profile,
    )
    assert decision.best_match in {"Short Iron Condor", "Bull Put Spread (credit)"}
    assert decision.risk_notes
    assert any("1.35" in note for note in decision.risk_notes)


def test_iv_040_over_hv_020_warns_and_keeps_the_structure() -> None:
    from app.services.strategy_engine import strategy_decision
    from app.services.strategy_recommendation import extreme_iv_overhang

    assert extreme_iv_overhang(0.40, 0.20) is True
    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        sentiment_score=70.0,
    )
    assert decision.best_match in {"Short Iron Condor", "Bull Put Spread (credit)"}
    assert decision.gate_reason is None
    assert any("40.00%" in note and "20.00%" in note for note in decision.risk_notes)
    assert decision.leg_structure


def test_matched_iv_and_hv_is_not_iv_crush() -> None:
    from app.services.strategy_recommendation import extreme_iv_overhang

    assert extreme_iv_overhang(0.20, 0.20) is False
    label = select_strategy(**{**_BOTH_ELIGIBLE, "iv": 0.20, "hv": 0.20})
    assert "IV Crush" not in label
    assert "NO TRADE" not in label


@pytest.mark.parametrize("hv", [None, 0, 0.0])
def test_missing_or_zero_hv_is_not_iv_crush(hv: float | None) -> None:
    from app.services.strategy_recommendation import extreme_iv_overhang

    assert extreme_iv_overhang(0.40, hv) is False
    label = select_strategy(**{**_BOTH_ELIGIBLE, "iv": 0.40, "hv": hv})
    assert "IV Crush" not in label


def test_percent_versus_fraction_is_not_false_iv_crush() -> None:
    """25 (%) against 0.20 (fraction) is the same 25% vs 20% pair — not a 125× overhang."""
    from app.services.strategy_recommendation import extreme_iv_overhang

    assert extreme_iv_overhang(25, 0.20) is False
    assert extreme_iv_overhang(0.25, 20) is False
    assert extreme_iv_overhang(40, 20) is True
    label = select_strategy(**{**_BOTH_ELIGIBLE, "iv": 25, "hv": 0.20})
    assert "IV Crush" not in label
    crushed = select_strategy(**{**_BOTH_ELIGIBLE, "iv": 40, "hv": 20})
    assert crushed in {"Short Iron Condor", "Bull Put Spread (credit)"}


def test_earnings_blackout_uses_its_own_reason_even_when_iv_is_rich() -> None:
    from app.services.strategy_engine import strategy_decision

    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="buy_premium",
        rsi=55.0,
        iv=0.40,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        catalyst_days=0,
    )
    assert decision.best_match
    assert "IV Crush" not in decision.best_match
    assert any("Earnings are within 1 day." in note for note in decision.risk_notes)


def test_wide_spread_uses_its_own_reason_not_iv_crush() -> None:
    from app.services.strategy_engine import strategy_decision

    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        spread_pct=18.0,
    )
    assert decision.best_match in {"Short Iron Condor", "Bull Put Spread (credit)"}
    assert any("spread" in note.lower() for note in decision.risk_notes)
    joined = " ".join(decision.risk_notes)
    assert "1.35" in joined
    # Spread alone does not turn a cleared setup into No Trade.
    still_a_match = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.20,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        spread_pct=18.0,
    )
    assert "NO TRADE" not in still_a_match.best_match
    assert "IV Crush" not in still_a_match.best_match


def test_high_iv_keeps_structure_legs_and_a_risk_note() -> None:
    from app.services.strategy_engine import strategy_decision

    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        sentiment_score=70.0,
    )
    assert decision.leg_structure
    layer = build_strategy_layer(
        strategy_name=decision.best_match,
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "XYZ",
            "spot": 100.0,
            "expiry": "2026-07-01",
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-07-01"},
            "contracts": CONTRACTS,
        },
        vol_layer={"iv": 0.40, "hv": 0.20, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 70},
        fundamentals_layer={"score": 60},
        tech_score=90.0,
        gate_reason=decision.gate_reason,
        leg_structure=decision.leg_structure,
        risk_notes=decision.risk_notes,
        auto_exec_threshold=85.0,
    )
    assert layer["selected_strategy"] == decision.best_match
    assert layer["metrics"]["legs"]
    assert "40.00%" in layer["why_it_fits"]
    assert "20.00%" in layer["why_it_fits"]
    blob = " ".join(
        [
            layer["selected_strategy"],
            layer["what_is_this"],
            layer["why_it_fits"],
            layer["how_to_execute"],
        ]
    )
    assert "IV Crush" not in blob
    assert any("1.35" in note for note in layer["risk_notes"])


def test_missing_quotes_are_not_described_as_iv_crush() -> None:
    from app.services.strategy_engine import strategy_decision

    decision = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.20,
        tech_score=90.0,
        confirmed_pattern_count=2,
        data_fresh=False,
    )
    assert "IV Crush" not in decision.best_match
    assert any("stale" in note.lower() for note in decision.risk_notes)


def test_score_below_auto_exec_minimum_is_not_iv_crush() -> None:
    label = select_strategy(**{**_BOTH_ELIGIBLE, "iv": 0.20, "hv": 0.20, "auto_exec_threshold": 99.0})
    assert "IV Crush" not in label
    assert "NO TRADE" not in label


def _payload_text(layer: dict) -> str:
    parts = [
        str(layer.get("selected_strategy") or ""),
        str(layer.get("what_is_this") or ""),
        str(layer.get("why_it_fits") or ""),
        str(layer.get("why_recommended") or ""),
        str(layer.get("how_to_execute") or ""),
        str(layer.get("narrative") or ""),
    ]
    return "\n".join(parts)


def test_aapl_bull_put_legs_keep_structure_name_and_payoff() -> None:
    """Sell 322.5 put / buy 320 put is a bull put credit spread, including when IV is only slightly above HV."""
    contracts = [
        {
            "side": "put",
            "strike": 322.5,
            "delta": -0.22,
            "bid": 1.10,
            "ask": 1.30,
            "symbol": "AAPL261016P00322500",
            "expiry": "2026-10-16",
        },
        {
            "side": "put",
            "strike": 320.0,
            "delta": -0.12,
            "bid": 0.66,
            "ask": 0.86,
            "symbol": "AAPL261016P00320000",
            "expiry": "2026-10-16",
        },
    ]
    layer = build_strategy_layer(
        strategy_name="Bull Put Spread (credit)",
        composite=66.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 325.0,
            "expiry": "2026-10-16",
            "recommendedContract": {"strike": 322.5, "side": "put", "expiry": "2026-10-16"},
            "contracts": contracts,
        },
        vol_layer={"iv": 0.2334, "hv": 0.224578, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        ticker="AAPL",
        auto_exec_threshold=40.0,
    )
    assert layer["selected_strategy"] == "Bull Put Spread (credit)"
    metrics = layer["metrics"]
    assert metrics["net_type"] == "credit"
    assert metrics["net_debit_credit"] == pytest.approx(0.44, abs=0.01)
    assert metrics["max_profit"] == pytest.approx(44, abs=0.01)
    assert metrics["max_loss"] == pytest.approx(206, abs=0.01)
    assert metrics["breakevens"][0] == pytest.approx(322.06, abs=0.01)
    text = _payload_text(layer)
    assert "NO TRADE" not in text
    assert "IV Crush" not in text
    assert "23.34%" in layer["why_it_fits"]
    assert "22.46%" in layer["why_it_fits"]
    assert layer["auto_exec_line"] == "Composite score 66 · Your auto-execute minimum 40 · Auto-execute eligible"
    assert layer["tradeable"] is True


def test_msft_long_call_legs_keep_structure_name_and_unlimited_profit() -> None:
    contracts = [
        {
            "side": "call",
            "strike": 515.0,
            "delta": 0.55,
            "bid": 11.00,
            "ask": 11.14,
            "symbol": "MSFT261016C00515000",
            "expiry": "2026-10-16",
        },
    ]
    layer = build_strategy_layer(
        strategy_name="Long Call",
        composite=66.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={
            "symbol": "MSFT",
            "spot": 510.0,
            "expiry": "2026-10-16",
            "recommendedContract": {"strike": 515.0, "side": "call", "expiry": "2026-10-16"},
            "contracts": contracts,
        },
        vol_layer={"iv": 0.2549, "hv": 0.216802, "iv_rank": 48},
        sentiment_layer={"bias": "bullish", "score_0_100": 62},
        fundamentals_layer={"score": 64},
        tech_score=74.0,
        ticker="MSFT",
        auto_exec_threshold=40.0,
    )
    assert layer["selected_strategy"] == "Long Call"
    metrics = layer["metrics"]
    assert metrics["net_type"] == "debit"
    assert metrics["net_debit_credit"] == pytest.approx(11.07, abs=0.01)
    assert metrics["max_loss"] == pytest.approx(1107, abs=0.01)
    assert metrics["max_profit"] is None
    assert metrics["max_profit_unlimited_allowed"] is True
    assert metrics["breakevens"][0] == pytest.approx(526.07, abs=0.01)
    text = _payload_text(layer)
    assert "NO TRADE" not in text
    assert "IV Crush" not in text
    assert "25.49%" in layer["why_it_fits"]
    assert "21.68%" in layer["why_it_fits"]
    assert "Buy the 515 call" in layer["how_to_execute"]


def test_score_below_threshold_still_returns_the_structure() -> None:
    layer = build_strategy_layer(
        strategy_name="Bull Call Spread",
        composite=62.0,
        direction="bullish",
        vol_signal="buy_premium",
        chain_analysis={
            "symbol": "XYZ",
            "spot": 100.0,
            "expiry": "2026-07-01",
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-07-01"},
            "contracts": CONTRACTS,
        },
        vol_layer={"iv": 0.22, "hv": 0.30, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 60},
        tech_score=80.0,
        ticker="XYZ",
        auto_exec_threshold=70.0,
    )
    assert layer["selected_strategy"] == "Bull Call Spread"
    assert layer["metrics"]["legs"]
    assert layer["auto_exec_line"] is None
    assert "manual review required" in layer["why_recommended"]
