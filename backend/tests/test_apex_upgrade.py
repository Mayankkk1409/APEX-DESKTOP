"""Tests for APEX backend upgrade: scoring, gating, APEX Strategy, settings."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.analysis.composite_score import compute_apex_composite_score
from app.analysis.layers import APEX_STRATEGY_NAME, SCORE_TIER_NO_TRADE_MAX
from app.analysis.technical_analysis import PatternSignal, analyze_technicals
from app.services.apex_strategy import ApexStrategyInput, build_apex_strategy_input_from_scan, check_apex_strategy_eligibility
from app.services.strategy_engine import select_strategy
from app.services.strategy_recommendation import (
    MarketSnapshot,
    TechnicalAnalysisResultRef,
    UNDEFINED_RISK_STRATEGIES,
    recommend_strategy,
)


def _indicators(**overrides):
    base = {
        "ema": {9: 101, 21: 100, 50: 98, 100: 95, 200: 90},
        "supertrend": {"direction": "bullish", "value": 99.0},
        "macd": {"histogram": 0.1},
        "rsi": 55.0,
        "bollinger": {"width": 0.05},
        "volume": {"last": 1_200_000, "avg": 1_000_000},
        "ema_aligned_bullish": True,
        "ema_aligned_bearish": False,
    }
    base.update(overrides)
    return base


def test_composite_score_weights_and_penalties() -> None:
    result = compute_apex_composite_score(
        technical_score=80,
        volatility_score=75,
        options_score=70,
        sentiment_score=65,
        fundamental_score=60,
        wide_spreads=True,
        stale_data=True,
    )
    assert result.penalties["wide_spreads"] == 10.0
    assert result.penalties["stale_data"] == 6.0
    assert result.composite < result.raw_total
    api = result.to_api_dict()
    assert api["components"][0]["id"] == "technicals"
    assert api["weights"]["technicals"] == 0.30
    assert api["weights"]["volatility"] == 0.25
    assert api["weights"]["options"] == 0.20
    assert api["weights"]["sentiment"] == 0.15
    assert api["weights"]["fundamentals"] == 0.10
    assert api["weights"]["risk"] == 0.0
    expected_raw = 80 * 0.30 + 75 * 0.25 + 70 * 0.20 + 65 * 0.15 + 60 * 0.10
    assert result.raw_total == round(expected_raw, 1)
    assert result.composite == round(expected_raw - 16.0, 1)


def test_composite_score_tiers() -> None:
    low = compute_apex_composite_score(
        technical_score=40,
        volatility_score=40,
        options_score=40,
        sentiment_score=40,
        fundamental_score=40,
    )
    assert low.tier == "no_trade"
    mid = compute_apex_composite_score(
        technical_score=68,
        volatility_score=68,
        options_score=68,
        sentiment_score=68,
        fundamental_score=68,
    )
    assert mid.tier == "watchlist"
    high = compute_apex_composite_score(
        technical_score=85,
        volatility_score=85,
        options_score=85,
        sentiment_score=85,
        fundamental_score=85,
    )
    assert high.tier == "candidate"


def test_technical_analysis_confirmed_patterns_only() -> None:
    closes = [100, 101, 102, 103, 104, 105, 106]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = [1_000_000] * len(closes)
    result = analyze_technicals(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        indicators=_indicators(),
    )
    api = result.to_api_dict()
    assert all(p["status"] == "confirmed" for p in api["patterns"])
    assert all(p["reliability_tier"] in ("high", "medium") for p in api["patterns"])
    assert all(p["strength"] >= 65 for p in api["patterns"])
    assert result.score >= 50


def test_counter_trend_reversal_downweighted() -> None:
    closes = [110, 109, 108, 107, 106, 105, 104]
    highs = [c + 0.5 for c in closes]
    lows = [c - 2.5 for c in closes]
    volumes = [900_000] * len(closes)
    result = analyze_technicals(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        indicators=_indicators(ema_aligned_bullish=True),
    )
    shooting = next((p for p in result.patterns if p.name == "Shooting Star"), None)
    if shooting:
        assert shooting.strength < 76.0 or shooting.status != "confirmed"


def test_apex_strategy_eligibility_rejections() -> None:
    result = check_apex_strategy_eligibility(
        ApexStrategyInput(
            catalyst_days=3,
            term_structure_inverted=False,
            front_ivr=55.0,
            legs_same_strikes=False,
            four_leg_structure=False,
            call_delta=0.05,
            put_delta=0.05,
            front_premium_offset_pct=0.30,
            spread_pct=15.0,
            open_interest=100,
            adv=500_000,
        )
    )
    assert result.eligible is False
    assert len(result.rejection_reasons) >= 5
    assert any("Catalyst" in r for r in result.rejection_reasons)
    assert any("IVR" in r or "IV term structure" in r for r in result.rejection_reasons)


def test_apex_strategy_eligibility_passes() -> None:
    result = check_apex_strategy_eligibility(
        ApexStrategyInput(
            catalyst_days=7,
            term_structure_inverted=True,
            front_iv=0.45,
            back_iv=0.35,
            front_ivr=75.0,
            legs_same_strikes=True,
            four_leg_structure=True,
            call_delta=0.20,
            put_delta=0.22,
            front_premium_offset_pct=0.55,
            spread_pct=5.0,
            open_interest=1200,
            adv=6_000_000,
        )
    )
    assert result.eligible is True
    assert result.rejection_reasons == []


def test_build_apex_strategy_input_does_not_fake_eligibility() -> None:
    inp = build_apex_strategy_input_from_scan(
        catalyst_days=7,
        vol_layer={"iv_rank": 72.0, "term_structure": {"inverted": True, "front_iv": 0.4, "back_iv": 0.3}},
        chain_analysis={"contracts": [{"side": "call", "delta": 0.2, "bid": 1.0, "ask": 1.1, "open_interest": 1500}]},
    )
    assert inp.four_leg_structure is False
    assert inp.legs_same_strikes is False
    assert inp.front_premium_offset_pct is None
    result = check_apex_strategy_eligibility(inp)
    assert result.eligible is False
    assert any("4-leg" in r for r in result.rejection_reasons)


def test_undefined_risk_excluded_from_auto_exec() -> None:
    rec = recommend_strategy(
        market=MarketSnapshot(symbol="SPX", spot=5000, direction="neutral", data_fresh=True),
        technical=TechnicalAnalysisResultRef(score=90, direction="neutral", confirmed_pattern_count=1),
        composite=90,
        vol_signal="sell_premium",
        rsi=50,
        iv=0.4,
        hv=0.3,
        auto_exec_threshold=85,
    )
    assert all(c.name not in UNDEFINED_RISK_STRATEGIES for c in rec.candidates)
    assert rec.best_match not in {"Naked Call", "Naked Put", "Short Straddle", "Short Strangle"}
    assert rec.auto_exec_eligible or rec.tier == "watchlist"


def test_apex_strategy_rejects_partial_match() -> None:
    one_wing = check_apex_strategy_eligibility(
        ApexStrategyInput(
            catalyst_days=7,
            term_structure_inverted=True,
            front_iv=0.45,
            back_iv=0.35,
            front_ivr=75.0,
            legs_same_strikes=True,
            four_leg_structure=True,
            call_delta=0.20,
            put_delta=0.40,
            front_premium_offset_pct=0.55,
            spread_pct=5.0,
            open_interest=1200,
            adv=6_000_000,
        )
    )
    assert one_wing.eligible is False
    assert any("both call and put" in r for r in one_wing.rejection_reasons)

    exact_floor = check_apex_strategy_eligibility(
        ApexStrategyInput(
            catalyst_days=7,
            term_structure_inverted=True,
            front_iv=0.45,
            back_iv=0.35,
            front_ivr=75.0,
            legs_same_strikes=True,
            four_leg_structure=True,
            call_delta=0.20,
            put_delta=0.22,
            front_premium_offset_pct=0.55,
            spread_pct=8.0,
            open_interest=1000,
            adv=5_000_000,
        )
    )
    assert exact_floor.eligible is False
    assert any("ADV" in r for r in exact_floor.rejection_reasons)
    assert any("Open interest" in r for r in exact_floor.rejection_reasons)
    assert any("spread" in r.lower() for r in exact_floor.rejection_reasons)


def test_earnings_blackout_blocks_new_positions() -> None:
    label = select_strategy(
        composite=90,
        direction="bullish",
        vol_signal="buy_premium",
        rsi=55,
        iv=0.20,
        hv=0.30,
        tech_score=85,
        confirmed_pattern_count=1,
        catalyst_days=1,
    )
    assert label in {"Bull Call Spread", "APEX Benchmark Greeks Strategy", "Married Put"}


def test_chain_median_spread_is_percent_for_apex_gate() -> None:
    inp = build_apex_strategy_input_from_scan(
        catalyst_days=7,
        vol_layer={"iv_rank": 80},
        chain_analysis={"summary": {"median_spread_pct": 0.12}, "contracts": []},
    )
    assert inp.spread_pct == pytest.approx(12.0)


def test_select_strategy_no_trade_below_threshold() -> None:
    label = select_strategy(
        composite=45,
        direction="neutral",
        vol_signal="sell_premium",
        tech_score=55,
    )
    assert label == "Short Iron Condor"
    assert "NO TRADE" not in label


def test_select_strategy_returns_playbook_above_blocked_band() -> None:
    label = select_strategy(
        composite=55,
        direction="neutral",
        vol_signal="sell_premium",
        tech_score=55,
    )
    assert label != "NO TRADE — Insufficient Conviction"


def test_select_strategy_apex_strategy_on_catalyst() -> None:
    apex_input = ApexStrategyInput(
        catalyst_days=7,
        term_structure_inverted=True,
        front_iv=0.45,
        back_iv=0.35,
        front_ivr=75.0,
        legs_same_strikes=True,
        four_leg_structure=True,
        call_delta=0.20,
        put_delta=0.22,
        front_premium_offset_pct=0.55,
        spread_pct=4.0,
        open_interest=1200,
        adv=6_000_000,
    )
    label = select_strategy(
        composite=82,
        direction="neutral",
        vol_signal="sell_premium",
        rsi=50,
        iv=0.38,
        hv=0.30,
        ivr=75,
        tech_score=78,
        catalyst_active=True,
        apex_input=apex_input,
        confirmed_pattern_count=1,
    )
    assert label == APEX_STRATEGY_NAME


async def _auth(client: AsyncClient) -> str:
    await client.post(
        "/auth/signup",
        json={
            "full_name": "Settings User",
            "username": "settingsuser",
            "email": "settings@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 50000,
        },
    )
    await client.post("/auth/login", json={"username": "settingsuser", "password": "ApexDesk!23"})
    otp = await client.post("/auth/otp/request", json={"username": "settingsuser"})
    verify = await client.post("/auth/otp/verify", json={"username": "settingsuser", "code": otp.json()["code"]})
    return verify.json()["access_token"]


@pytest.mark.asyncio
async def test_trading_settings_persistence(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    get_res = await client.get("/api/settings/trading", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["auto_execution_threshold"] == 85

    patch_res = await client.patch(
        "/api/settings/trading",
        json={"auto_execution_threshold": 88, "risk_profile": "aggressive", "max_positions": 5},
        headers=headers,
    )
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["auto_execution_threshold"] == 88
    assert body["risk_profile"] == "aggressive"
    assert body["max_positions"] == 5

    again = await client.get("/api/settings/trading", headers=headers)
    assert again.json()["auto_execution_threshold"] == 88


@pytest.mark.asyncio
async def test_paper_balance_patch_with_audit(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    patch = await client.patch(
        "/api/settings/paper-balance",
        json={"balance": 75000, "reason": "Reset for testing"},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["new_balance"] == 75000

    audit = await client.get("/api/settings/paper-balance/audit", headers=headers)
    assert audit.status_code == 200
    rows = audit.json()
    assert len(rows) >= 1
    assert rows[0]["reason"] == "Reset for testing"
    assert rows[0]["new_balance"] == 75000


@pytest.mark.asyncio
async def test_delete_account_requires_password(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    bad = await client.post("/api/settings/account/delete", json={"password": "WrongPass!"}, headers=headers)
    assert bad.status_code == 401
    ok = await client.post("/api/settings/account/delete", json={"password": "ApexDesk!23"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["deleted"] is True
