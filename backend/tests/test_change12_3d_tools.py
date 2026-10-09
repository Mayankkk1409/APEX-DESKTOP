"""Checks for the Change 12 ledger and sub-score scripts.

These tests read the captured fixture or a ledger note. They do not build a chain.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "change12_qa_replay.json"
GAMMA_NAMES = ("JPM", "GS", "C", "JNJ", "UNH", "BAC", "WFC", "MS", "BLK", "PLD")


def _load(name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


explain = _load("explain_change12_gamma", "explain_change12_gamma.py")
subscores = _load("report_change12_subscores", "report_change12_subscores.py")


def test_missing_iv_rank_is_a_data_defect() -> None:
    classified = explain.classify_gate_note(
        "Front-week IV rank is missing, so the 70 minimum cannot pass."
    )
    assert classified["result"] == "data_defect"
    assert classified["detail"].startswith("measured=absent")
    assert "above 70" in classified["detail"]
    assert "not a strategy verdict" in classified["comment"]


def test_missing_iv_ratio_is_a_data_defect() -> None:
    classified = explain.classify_gate_note(
        "Front-week IV divided by back-week IV is missing, so the 1.25 minimum cannot pass."
    )
    assert classified["result"] == "data_defect"
    assert "measured=absent" in classified["detail"]
    assert classified["detail"].endswith("at least 1.25")
    failed = explain.classify_gate_note(
        "Front-week IV divided by back-week IV is 1.11, below 1.25."
    )
    assert failed["result"] == "fail"
    assert failed["detail"] == "measured=1.11; threshold=at least 1.25"


def test_history_gap_is_not_filled_in() -> None:
    classified = explain.classify_gate_note(
        "Earnings move history is missing; the last 8 reports are not in the data."
    )
    assert classified["result"] == "fail_closed"
    assert "measured=absent" in classified["detail"]
    assert "not invented" in classified["comment"]
    assert "actual_move" not in classified["detail"]


def test_empty_ledger_says_so() -> None:
    text = explain.explain_ticker("JPM", {"ticker": "JPM", "ledger_gamma": [], "candidates": []})
    assert "no ledger rows" in text
    text = explain.explain_ticker("GS", {"ticker": "GS", "evaluation_ledger": []})
    assert "no ledger rows" in text
    assert "no snapshot" in explain.explain_ticker("C", None)


def test_fixture_explains_each_catalyst_name() -> None:
    payload = json.loads(FIXTURE.read_text())
    text = explain.render_report(payload)
    assert "actual_move" not in text
    for ticker in GAMMA_NAMES:
        block = text.split(f"{ticker}:")[1].split("\n\n")[0]
        assert "no ledger rows" not in block
        assert "selected: no" in block
        assert "iv_rank: pass" in block
        assert "history: fail_closed" in block
        assert "were not invented" in block
        assert "data defect" not in block


def test_absent_pillar_is_not_invented() -> None:
    payload = {
        "rows": [
            {
                "ticker": "MSFT",
                "summary": {"components": {"technicals": 10.0, "volatility": None, "options": 40.0}},
            }
        ]
    }
    text = subscores.render_distribution(payload, ["MSFT", "NVDA"])
    assert "technical: n=1 mean=10.00" in text
    assert "volatility: n=0" in text
    assert "MSFT (pillar absent)" in text
    assert "NVDA (no snapshot)" in text
    assert "greeks: n=1 mean=40.00" in text
    assert "sentiment: n=0" in text
    assert "fundamental: n=0" in text
    assert "Weights were not changed" in text
    assert "does not write weights" in text


def test_fixture_subscore_distribution_uses_captured_numbers() -> None:
    payload = json.loads(FIXTURE.read_text())
    tickers = subscores.qa_tickers()
    assert len(tickers) == 50
    text = subscores.render_distribution(payload, tickers)
    technicals = [float(row["summary"]["components"]["technicals"]) for row in payload["rows"]]
    mean = statistics.fmean(technicals)
    assert f"technical: n=50 mean={mean:.2f}" in text
    for label in ("technical", "volatility", "greeks", "sentiment", "fundamental"):
        section = text.split(f"{label}:")[1].split("\n\n")[0]
        assert f"{label}: n=50" in text
        assert "absent: none" in section
    assert "Weights were not changed" in text
    assert "technicals 30%" in text
    assert "does not write weights" in text


def test_scripts_print_the_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    assert explain.main([str(FIXTURE)]) == 0
    gamma = capsys.readouterr().out
    assert "JPM:" in gamma
    assert "PLD:" in gamma
    assert subscores.main([str(FIXTURE)]) == 0
    report = capsys.readouterr().out
    assert "technical: n=50" in report
