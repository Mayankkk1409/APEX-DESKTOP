"""Change 12 phase 3 closeout: narrative guard, one vol rule, event-vega rank."""

from __future__ import annotations

import inspect

from app.analysis.gate_config import assess_vol_regime
from app.contracts import canAutoExecute
from app.services.evidence_ledger import get, reset_ledger
from app.services.executability import quote_problem
from app.services.fills import execute_market_fill
from app.services.narrative_guard import check_narrative, rejections, reset_rejections
from app.services.strategy_engine import build_strategy_layer, strategy_decision
from app.services.strategy_recommendation import GAMMA_TRAMPOLINE_NAME, _rank_candidates
from app.services.volatility_intel import _iv_hv_signal


def test_generated_card_text_passes_the_ledger_check() -> None:
    reset_ledger("AAPL")
    reset_rejections()
    layer = build_strategy_layer(
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
                    "iv": 0.3031,
                }
            ],
        },
        vol_layer={"iv": 0.3031, "atm_iv": 0.3031, "hv": 0.2038, "iv_rank": 43.2, "feed": "indicative"},
        sentiment_layer={"bias": "bearish", "score_0_100": 40},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="AAPL",
    )
    for field in ("why_it_fits", "how_to_execute", "what_is_this", "auto_exec_line", "narrative"):
        checked = check_narrative(str(layer[field]), scan_id="AAPL", strategy_id="Long Put")
        assert checked.accepted, (field, checked.unmatched, checked.qualitative)
    for note in layer["risk_notes"]:
        checked = check_narrative(note, scan_id="AAPL", strategy_id="Long Put")
        assert checked.accepted, (note, checked.unmatched, checked.qualitative)
    stored = get("AAPL")
    assert any(row.fn == "build_strategy_layer" and row.kind == "value" for row in stored)
    assert any(row.inputs and row.timestamp and row.source for row in stored if row.fn == "build_strategy_layer")


def test_invented_card_number_is_rejected_and_logged() -> None:
    reset_ledger("MSFT")
    reset_rejections()
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
        vol_layer={"iv": 0.22, "hv": 0.21, "iv_rank": 40},
        sentiment_layer={"bias": "bullish", "score_0_100": 60},
        fundamentals_layer={"score": 50},
        tech_score=70.0,
        ticker="MSFT",
        risk_notes=["Invented probability 99.9 percent."],
    )
    assert "99.9" not in " ".join(layer["risk_notes"])
    assert rejections("MSFT")


def test_five_point_band_replaces_the_ten_point_band() -> None:
    rich = _iv_hv_signal(0.27, 0.20)
    fair = _iv_hv_signal(0.27, 0.225)
    cheap = _iv_hv_signal(0.18, 0.25)
    assert rich["signal"] == "sell_premium"
    assert fair["signal"] == "fair"
    assert cheap["signal"] == "buy_premium"
    assert "between_bands" not in {rich["signal"], fair["signal"], cheap["signal"]}
    assert "10" not in rich["reason"].split("Rule:")[0]
    view = assess_vol_regime(iv=0.27, hv=0.20, iv_rank=None)
    assert view.short == "sell premium"
    assert view.iv_minus_hv_pts == 7.0
    assert _iv_hv_signal(0.25, 0.25)["signal"] == "fair"


def test_event_vega_penalty_changes_the_first_name() -> None:
    base = dict(
        composite=60.0,
        direction="bullish",
        vol_signal="fair",
        rsi=50.0,
        iv=0.25,
        hv=0.25,
        ivr=40.0,
        tech_score=70.0,
        sentiment_score=50.0,
        catalyst_active=True,
        delta_theta_ratio=None,
        apex_eligible=True,
        back_month_available=True,
    )
    plain = _rank_candidates(**base)
    assert plain[0].name == GAMMA_TRAMPOLINE_NAME
    span = {
        "earnings_date": "2026-10-20",
        "short_expiry": "2026-10-16",
        "long_expiry": "2026-11-20",
        "long_leg_iv": 0.50,
        "normal_iv": 0.25,
    }
    penalized = _rank_candidates(**base, event_span=span)
    assert penalized[0].name == "Married Put"
    gamma = next(row for row in penalized if row.name == GAMMA_TRAMPOLINE_NAME)
    assert gamma.score < plain[0].score
    note = next(item for item in gamma.gate_notes if item.startswith("Event-vega penalty:"))
    assert "2026-11-20" in note
    assert "2026-10-20" in note
    assert "25.00" in note
    unmeasured = _rank_candidates(
        **base,
        event_span={
            "earnings_date": "2026-10-20",
            "short_expiry": "2026-10-16",
            "long_expiry": "2026-11-20",
            "long_leg_iv": None,
            "normal_iv": None,
        },
    )
    assert unmeasured[0].name == GAMMA_TRAMPOLINE_NAME
    missing = next(row for row in unmeasured if row.name == GAMMA_TRAMPOLINE_NAME)
    assert missing.score == plain[0].score
    assert any("could not be measured" in item for item in missing.gate_notes)


def test_event_vega_penalty_is_on_the_score_ledger() -> None:
    reset_ledger("TSLA")
    strategy_decision(
        composite=60.0,
        direction="bullish",
        vol_signal="fair",
        rsi=50.0,
        iv=0.25,
        hv=0.25,
        ivr=40.0,
        tech_score=70.0,
        catalyst_active=True,
        apex_input=None,
        back_month_available=True,
        symbol="TSLA",
        event_span={
            "earnings_date": "2026-10-28",
            "short_expiry": "2026-10-23",
            "long_expiry": "2026-11-20",
            "long_leg_iv": 0.40,
            "normal_iv": 0.22,
        },
    )
    rows = get("TSLA")
    assert any("event_vega_penalty" in row.key for row in rows)


def test_can_auto_execute_contract_delegates() -> None:
    allowed = canAutoExecute(
        {"composite_score": 90, "executable": True, "validation_passed": True},
        {"auto_execution_threshold": 85},
    )
    blocked = canAutoExecute(
        {"composite_score": 90, "executable": False, "validation_passed": True, "executability_reason": "quote not current"},
        {"auto_execution_threshold": 50},
    )
    assert allowed.eligible is True
    assert allowed.reasons == []
    assert blocked.eligible is False
    assert blocked.reasons


def test_order_path_cannot_skip_the_quote_check() -> None:
    assert "skip_quote_check" not in inspect.signature(execute_market_fill).parameters


def test_priced_quote_without_a_timestamp_is_not_fresh() -> None:
    problem = quote_problem({"price": 4.02, "bid": 3.9, "ask": 4.1, "as_of": ""})
    assert problem is not None
    assert "unknown time" in problem


def test_back_week_iv_is_read_from_the_back_chain() -> None:
    from app.services.apex_strategy import build_apex_strategy_input_from_scan

    built = build_apex_strategy_input_from_scan(
        catalyst_days=8,
        vol_layer={"iv": 0.40, "iv_rank": 80, "adv": 8_000_000},
        chain_analysis={"spot": 100, "contracts": [{"side": "call", "strike": 100, "iv": 0.40, "bid": 2, "ask": 2.1}]},
        back_month_contracts=[{"side": "call", "strike": 100, "iv": 0.25, "bid": 3, "ask": 3.1}],
        earnings_date_confirmed=True,
        spot=100,
    )
    assert built.front_iv == 0.40
    assert built.back_iv == 0.25
    assert built.earnings_date_confirmed is True
    assert built.adv == 8_000_000
