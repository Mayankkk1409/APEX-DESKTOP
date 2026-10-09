"""Change 12 agent 4A: the trader card is copy, not the evidence ledger.

A rejected narrative falls back to a short knowledge-base sentence for the
selected strategy with that strategy's values. It must never join the ledger
rows. The ledger stays on ``GET /api/ledger`` and in the rejection log.
"""

from __future__ import annotations

import pytest

from app.services.evidence_ledger import get, record_card_value, record_score, reset_ledger
from app.services.narrative_guard import check_narrative, rejections, reset_rejections
from app.services.strategy_engine import build_strategy_layer

# Strings the user saw on the MDB and NFLX cards. None of them belong in card copy.
_DUMP_MARKERS = (
    "from strategy_recommendation",
    "via recommend_strategy",
    "via build_strategy_layer",
    "data_freshness is",
    ":score is 0",
    "payoff_grid",
    "measured True",
)

_META = {
    "source": "strategy_recommendation",
    "feed": "indicative",
    "timestamp": "2026-10-05T14:00:00Z",
    "fn": "recommend_strategy",
}

_CANDIDATES = (
    "collar",
    "long_call",
    "long_put",
    "bull_put_spread_credit",
    "short_iron_condor",
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_ledger()
    reset_rejections()
    yield
    reset_ledger()
    reset_rejections()


def _seed_recommendation_rows(scan_id: str) -> None:
    """The rows a scan records: gate booleans and a zero score per unselected strategy."""
    for gate in ("data_freshness", "liquidity", "spread_cap", "earnings_blackout"):
        record_card_value(scan_id, gate, True, inputs={"measured": True, "passed": True}, **_META)
    for strategy_id in _CANDIDATES:
        record_score(scan_id, strategy_id, "score", 0, **_META)


def _mdb_layer(**extra: object) -> dict:
    return build_strategy_layer(
        strategy_name="Collar",
        composite=58.0,
        direction="neutral",
        vol_signal="fair",
        chain_analysis={
            "symbol": "MDB",
            "spot": 330.0,
            "expiry": "2026-11-20",
            "shares_held": 100,
            "contracts": [
                {
                    "symbol": "MDB261120C00350000",
                    "side": "call",
                    "strike": 350.0,
                    "expiry": "2026-11-20",
                    "delta": 0.30,
                    "bid": 8.0,
                    "ask": 8.3,
                    "iv": 0.42,
                },
                {
                    "symbol": "MDB261120P00310000",
                    "side": "put",
                    "strike": 310.0,
                    "expiry": "2026-11-20",
                    "delta": -0.28,
                    "bid": 7.5,
                    "ask": 7.8,
                    "iv": 0.44,
                },
            ],
        },
        vol_layer={"iv": 0.42, "atm_iv": 0.42, "hv": 0.33, "iv_rank": 61.0, "feed": "indicative"},
        sentiment_layer={"bias": "bullish", "score_0_100": 61},
        fundamentals_layer={"score": 52},
        tech_score=44.0,
        ticker="MDB",
        **extra,
    )


def _nflx_layer(**extra: object) -> dict:
    return build_strategy_layer(
        strategy_name="Long Call",
        composite=64.0,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "NFLX",
            "spot": 1200.0,
            "expiry": "2026-11-20",
            "contracts": [
                {
                    "symbol": "NFLX261120C01250000",
                    "side": "call",
                    "strike": 1250.0,
                    "expiry": "2026-11-20",
                    "delta": 0.44,
                    "bid": 30.0,
                    "ask": 31.0,
                    "iv": 0.38,
                }
            ],
        },
        vol_layer={"iv": 0.38, "atm_iv": 0.38, "hv": 0.31, "iv_rank": 48.0, "feed": "indicative"},
        sentiment_layer={"bias": "bullish", "score_0_100": 58},
        fundamentals_layer={"score": 61},
        tech_score=66.0,
        ticker="NFLX",
        **extra,
    )


def _card_texts(layer: dict) -> dict[str, str]:
    """Every user-facing text field on the trader card."""
    fields = {
        "why_it_fits": str(layer.get("why_it_fits") or ""),
        "how_to_use": str(layer.get("how_to_execute") or ""),
        "what_is_this": str(layer.get("what_is_this") or ""),
        "risk_review": str(layer.get("auto_exec_line") or ""),
        "narrative": str(layer.get("narrative") or ""),
        "outlook": str(layer.get("outlook") or ""),
    }
    for index, note in enumerate(layer.get("risk_notes") or []):
        fields[f"risk_notes[{index}]"] = str(note)
    return fields


@pytest.mark.parametrize("build", [_mdb_layer, _nflx_layer], ids=["MDB", "NFLX"])
def test_card_copy_never_carries_the_evidence_ledger(build) -> None:
    scan_id = "MDB" if build is _mdb_layer else "NFLX"
    _seed_recommendation_rows(scan_id)
    # An ungrounded figure forces every guarded text path onto the fallback.
    layer = build(risk_notes=["Invented figure 999.9."])
    texts = _card_texts(layer)
    assert texts["why_it_fits"]
    assert any(name.startswith("risk_notes") for name in texts)
    for name, text in texts.items():
        for marker in _DUMP_MARKERS:
            assert marker not in text, (name, marker, text)
        assert "999.9" not in text, name
    # The ledger itself still holds the rows the card refused to print.
    keys = [entry.key for entry in get(scan_id)]
    assert "data_freshness" in keys
    assert f"{_CANDIDATES[0]}:score" in keys
    assert any(row["unmatched"] for row in rejections(scan_id))


@pytest.mark.parametrize("build", [_mdb_layer, _nflx_layer], ids=["MDB", "NFLX"])
def test_fallback_is_short_and_names_the_strategy_once(build) -> None:
    scan_id = "MDB" if build is _mdb_layer else "NFLX"
    _seed_recommendation_rows(scan_id)
    layer = build(risk_notes=["Invented figure 999.9."])
    name = str(layer["selected_strategy"])
    note = str((layer.get("risk_notes") or [""])[0])
    assert note.count("\n") == 0
    assert len(note.split(". ")) <= 3, note
    assert note.lower().count(name.lower()) <= 1, note
    checked = check_narrative(note, scan_id=scan_id, strategy_id=name)
    assert checked.accepted, checked.unmatched


def test_rejected_narrative_falls_back_to_the_selected_strategy_sentence() -> None:
    _seed_recommendation_rows("MDB")
    record_card_value(
        "MDB",
        "composite",
        58.0,
        inputs={"measured": 58.0, "strategy": "Collar"},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_strategy_layer",
    )
    record_card_value(
        "MDB",
        "iv",
        42.0,
        inputs={"measured": 42.0, "strategy": "Collar"},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_strategy_layer",
    )
    result = check_narrative(
        "The probability of profit is 99.9 percent.",
        scan_id="MDB",
        strategy_id="Collar",
    )
    assert result.accepted is False
    assert result.used_fallback is True
    assert "99.9" not in result.text
    for marker in _DUMP_MARKERS:
        assert marker not in result.text, marker
    # Knowledge-base copy for the selected strategy, filled with its own figures.
    from app.strategies.knowledge_base import entry_for

    kb = entry_for("Collar")
    assert kb is not None
    assert any(sentence and sentence in result.text for sentence in kb.why_it_fits.split(". "))
    assert "The composite is 58 with IV 42 percent." in result.text
    assert "Payoff is the model grid" not in result.text
    assert result.text.lower().count("collar") <= 1
    assert check_narrative(result.text, scan_id="MDB", strategy_id="Collar").accepted is True


def test_fallback_keeps_the_selected_composite_not_an_earlier_row() -> None:
    _seed_recommendation_rows("MDB")
    record_card_value(
        "MDB",
        "composite",
        11.1,
        inputs={"measured": 11.1},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T13:00:00Z",
        fn="build_strategy_layer",
    )
    record_card_value(
        "MDB",
        "composite",
        58.0,
        inputs={"measured": 58.0, "strategy": "Collar"},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_strategy_layer",
    )
    record_card_value(
        "MDB",
        "iv",
        0.42,
        inputs={"measured": 0.42, "strategy": "Collar"},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_strategy_layer",
    )
    record_card_value(
        "MDB",
        "hv",
        0.33,
        inputs={"measured": 0.33, "strategy": "Collar"},
        source="strategy_layer",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_strategy_layer",
    )
    result = check_narrative("Invented figure 999.9.", scan_id="MDB", strategy_id="Collar")
    assert "11.1" not in result.text
    assert "999.9" not in result.text
    assert "The composite is 58 with IV 42 percent and HV 33 percent." in result.text
    for marker in _DUMP_MARKERS:
        assert marker not in result.text, marker


def test_fallback_without_a_strategy_does_not_quote_the_ledger() -> None:
    _seed_recommendation_rows("MDB")
    result = check_narrative("Invented ticker ZZZZ.", scan_id="MDB", strategy_id=None)
    assert result.accepted is False
    for marker in _DUMP_MARKERS:
        assert marker not in result.text, marker
    assert "ZZZZ" not in result.text


def test_why_it_fits_states_iv_versus_hv_once_and_skips_the_ledger() -> None:
    """The visible Why it fits line is one comparison, not the rule essay twice."""
    from app.analysis.gate_config import vol_regime_rule_text

    layer = build_strategy_layer(
        strategy_name="Bull Put Spread (credit)",
        composite=52.8,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "MDB",
            "spot": 342.0,
            "expiry": "2026-10-09",
            "recommendedContract": {"strike": 340.0, "side": "put", "expiry": "2026-10-09"},
            "contracts": [
                {
                    "symbol": "MDB261009P00340000",
                    "side": "put",
                    "strike": 340.0,
                    "expiry": "2026-10-09",
                    "delta": -0.22,
                    "bid": 1.10,
                    "ask": 1.54,
                    "iv": 0.40,
                },
                {
                    "symbol": "MDB261009P00337500",
                    "side": "put",
                    "strike": 337.5,
                    "expiry": "2026-10-09",
                    "delta": -0.18,
                    "bid": 0.55,
                    "ask": 1.90,
                    "iv": 0.42,
                },
            ],
        },
        vol_layer={"iv": 0.3031, "atm_iv": 0.3031, "hv": 0.2038, "iv_rank": 43.2, "feed": "indicative"},
        sentiment_layer={"bias": "bullish", "score_0_100": 61},
        fundamentals_layer={"score": 52},
        tech_score=69.0,
        ticker="MDB",
        auto_exec_threshold=85.0,
    )
    text = str(layer["why_it_fits"])
    rule = vol_regime_rule_text()
    assert text.count(rule) < 2
    assert text.count("IV versus HV is primary") <= 1
    assert text.count("30.31%") == 1
    assert text.count("20.38%") == 1
    wide = build_strategy_layer(
        strategy_name="Bull Put Spread (credit)",
        composite=52.8,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "MDB",
            "spot": 342.0,
            "expiry": "2026-10-09",
            "recommendedContract": {"strike": 340.0, "side": "put", "expiry": "2026-10-09"},
            "contracts": [
                {
                    "symbol": "MDB261009P00340000",
                    "side": "put",
                    "strike": 340.0,
                    "expiry": "2026-10-09",
                    "delta": -0.22,
                    "bid": 1.10,
                    "ask": 1.54,
                    "iv": 0.5934,
                },
                {
                    "symbol": "MDB261009P00337500",
                    "side": "put",
                    "strike": 337.5,
                    "expiry": "2026-10-09",
                    "delta": -0.18,
                    "bid": 0.55,
                    "ask": 1.90,
                    "iv": 0.5934,
                },
            ],
        },
        vol_layer={"iv": 0.5934, "atm_iv": 0.5934, "hv": 0.8687, "iv_rank": 100, "feed": "indicative"},
        sentiment_layer={"bias": "bullish", "score_0_100": 61},
        fundamentals_layer={"score": 52},
        tech_score=69.0,
        ticker="MDB",
        auto_exec_threshold=85.0,
    )
    wide_text = str(wide["why_it_fits"])
    assert wide_text.count(rule) < 2
    assert wide_text.count("59.34%") == 1
    assert wide_text.count("86.87%") == 1
    assert "breaks the tie" not in wide_text
    assert "sell premium" not in wide_text
    assert "is cheap" in wide_text
    assert "Failed checks:" in text
    assert text.lower().count("failed checks:") == 1
    assert "NOT EXECUTABLE" not in text
    assert "Fundamentals score" not in text
    assert "on 0–100 scale" not in text
    assert "on 0-100 scale" not in text
    for marker in _DUMP_MARKERS:
        assert marker not in text, marker
    for field in (
        "what_is_this",
        "how_to_execute",
        "narrative",
        "auto_exec_line",
        "outlook",
        "selection_rationale",
    ):
        body = str(layer.get(field) or "")
        for marker in _DUMP_MARKERS:
            assert marker not in body, (field, marker)
