"""Change 12 agent 3A: prove the narrative guard on every strategy-card text path.

Item (a) is already implemented. These tests do not change matching.
"""

from __future__ import annotations

import pytest
from loguru import logger

from app.services.evidence_ledger import reset_ledger
from app.services.narrative_guard import check_narrative, rejections, reset_rejections
from app.services.strategy_engine import _guard_card_text, _guard_strategy_card, build_strategy_layer

_KB_MARK = "The long option supplies directional exposure"
_LEDGER_FACT = "composite is 59 "

# Arguments _guard_strategy_card and the outlook _guard_card_text pass to check_narrative.
_PATHS = (
    "why_it_fits",
    "how_to_use",
    "risk_notes",
    "summary",
    "risk_review",
    "narrative",
    "outlook",
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_ledger()
    reset_rejections()
    yield
    reset_ledger()
    reset_rejections()


def _aapl_chain() -> dict:
    return {
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
    }


def _aapl_layer(**extra: object) -> dict:
    return build_strategy_layer(
        strategy_name="Long Put",
        composite=59.0,
        direction="bearish",
        vol_signal="fair",
        chain_analysis=_aapl_chain(),
        vol_layer={"iv": 0.3031, "atm_iv": 0.3031, "hv": 0.2038, "iv_rank": 43.2, "feed": "indicative"},
        sentiment_layer={"bias": "bearish", "score_0_100": 40},
        fundamentals_layer={"score": 55},
        tech_score=60.0,
        ticker="AAPL",
        **extra,
    )


def _guarded(sentence: str) -> dict[str, str]:
    """Send one sentence through every text path the strategy card guard owns."""
    reset_ledger("INJECT")
    reset_rejections()
    fit, execution, notes, summary, status_line, narrative = _guard_strategy_card(
        scan_id="INJECT",
        strategy_name="Long Put",
        fit=sentence,
        execution=sentence,
        notes=[sentence],
        summary=sentence,
        status_line=sentence,
        narrative=sentence,
        figures={"composite": 59.0, "symbol": "AAPL", "expiry": "2026-10-30", "iv": 30.31},
        feed="indicative",
        quote_as_of="2026-10-05T14:00:00Z",
    )
    outlook = _guard_card_text(sentence, scan_id="INJECT", strategy_name="Long Put")
    return {
        "why_it_fits": fit,
        "how_to_use": execution,
        "risk_notes": notes[0],
        "summary": summary,
        "risk_review": status_line,
        "narrative": narrative,
        "outlook": outlook,
    }


def _assert_fallback(paths: dict[str, str], token: str) -> None:
    assert set(paths) == set(_PATHS)
    logged = rejections("INJECT")
    assert len(logged) == len(paths)
    for name, text in paths.items():
        assert token not in text, name
        assert _KB_MARK in text, name
        assert _LEDGER_FACT in text, name
        again = check_narrative(text, scan_id="INJECT", strategy_id="Long Put")
        assert again.accepted, name
        assert again.unmatched == (), (name, again.unmatched)
        assert again.used_fallback is False
    assert all(any(token in item for item in row["unmatched"]) for row in logged)


def test_injected_fake_number_is_rejected_on_every_guarded_text_path() -> None:
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(message.record["message"]), level="WARNING")
    try:
        paths = _guarded("Invented figure 999.9.")
    finally:
        logger.remove(sink)
    _assert_fallback(paths, "999.9")
    assert sum("narrative rejected" in line and "999.9" in line for line in lines) == len(paths)

    reset_ledger("AAPL")
    reset_rejections()
    layer = _aapl_layer(risk_notes=["Invented figure 999.9."])
    shown = " ".join(
        [
            str(layer["why_it_fits"]),
            str(layer["how_to_execute"]),
            str(layer["what_is_this"]),
            str(layer["outlook"]),
            str(layer["narrative"]),
            str(layer["auto_exec_line"]),
            " ".join(layer["risk_notes"]),
        ]
    )
    assert "999.9" not in shown
    assert any("999.9" in item for row in rejections("AAPL") for item in row["unmatched"])


@pytest.mark.parametrize(
    ("token", "sentence"),
    [
        ("99.9", "Invented probability 99.9 percent."),
        ("1999-01-01", "Invented date 1999-01-01."),
        ("ZZZZ", "Invented ticker ZZZZ."),
    ],
)
def test_unmatched_percent_date_and_ticker_fall_back_on_every_path(token: str, sentence: str) -> None:
    paths = _guarded(sentence)
    _assert_fallback(paths, token)


def test_aapl_strategy_layer_card_has_zero_unmatched_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = check_narrative

    def spy(text: str, *, scan_id: str, strategy_id: str | None = None):
        calls.append(text)
        return real(text, scan_id=scan_id, strategy_id=strategy_id)

    monkeypatch.setattr("app.services.narrative_guard.check_narrative", spy)
    layer = _aapl_layer()
    fields = {
        "why_it_fits": layer["why_it_fits"],
        "how_to_use": layer["how_to_execute"],
        "risk_notes": layer["risk_notes"],
        "summary": layer["what_is_this"],
        "risk_review": layer["auto_exec_line"],
        "narrative": layer["narrative"],
        "outlook": layer["outlook"],
    }
    assert layer["why_recommended"] == layer["why_it_fits"]
    assert fields["risk_notes"], "the AAPL card should carry the guarded risk notes"
    for name, value in fields.items():
        texts = value if isinstance(value, list) else [value]
        for text in texts:
            assert text in calls, name
            checked = check_narrative(str(text), scan_id="AAPL", strategy_id="Long Put")
            assert checked.unmatched == (), (name, checked.unmatched, text)
            assert checked.qualitative == (), (name, checked.qualitative)
            assert checked.accepted
    assert rejections("AAPL") == []
