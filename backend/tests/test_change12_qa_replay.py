"""Replay of the 50-row QA sheet against captured market data.

Rows whose capture failed, or that have no snapshot, are skipped with that
reason. The fixture is the provider payload from the capture script. It is
not a synthetic chain.

An xfail on this module is only for a failure caused by production code this
branch is not allowed to edit, and the reason names that owner. None are
marked unless a run shows that cause. Assertions are not loosened to pass.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.analysis.gate_config import IV_MISMATCH_VOL_POINTS, assess_vol_regime
from app.services.fundamentals_layer import IR_CONFIRMED
from app.strategies.registry import STRATEGY_REGISTRY

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "change12_qa_replay.json"
CSV_PATH = Path(__file__).resolve().parents[2] / "docs" / "qa" / "APEX_QA_Test_Results.csv"
GAMMA = "Gamma Trampoline™"
GAMMA_NAMES = ("JPM", "GS", "C", "JNJ", "UNH", "BAC", "WFC", "MS", "BLK", "PLD")
STOCK_NAMES = ("Married Put", "Covered Call", "Collar", "Protective Collar")
ETFS = {"SPY", "QQQ"}


def _fixture_rows() -> dict[str, dict]:
    if not FIXTURE.is_file():
        return {}
    payload = json.loads(FIXTURE.read_text())
    return {row["ticker"]: row for row in payload.get("rows") or [] if isinstance(row, dict) and row.get("ticker")}


def _cases() -> list[tuple[str, dict | None]]:
    by_ticker = _fixture_rows()
    cases: list[tuple[str, dict | None]] = []
    with CSV_PATH.open() as handle:
        for record in csv.DictReader(handle):
            ticker = str(record["Ticker"]).strip()
            cases.append((ticker, by_ticker.get(ticker)))
    return cases


CASES = _cases()


def _spec_by_name() -> dict:
    return {spec.display_name: spec for spec in STRATEGY_REGISTRY.values()}


def _is_none_word(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == "none"


def _regime_side(text: object) -> str:
    """Map the short label and the card phrase onto one side of the ±5 rule."""
    value = str(text or "")
    if value in {"IV much above HV", "sell premium"}:
        return "sell"
    if value in {"IV much below HV", "buy premium"}:
        return "buy"
    if value in {"fair", "IV near HV"}:
        return "near"
    return value


@pytest.mark.parametrize("ticker,row", CASES, ids=[ticker for ticker, _row in CASES])
def test_qa_replay_row(ticker: str, row: dict | None) -> None:
    if row is None:
        pytest.skip(f"{ticker}: no snapshot in the fixture")
    if row.get("error"):
        pytest.skip(f"{ticker} {row.get('expiry')}: {row['error']}")
    summary = row.get("summary")
    if not isinstance(summary, dict):
        pytest.skip(f"{ticker}: snapshot has no summary")

    status = summary.get("status")
    eligible = bool(summary.get("eligible"))
    line = str(summary.get("eligibility") or "")
    assert not (status == "NOT EXECUTABLE" and eligible)
    assert not (status == "NOT EXECUTABLE" and "auto-execute eligible" in line.lower())

    spec = _spec_by_name().get(summary.get("strategy"))
    assert spec is not None
    option_legs = int(summary["leg_count"])
    equity_legs = len(summary.get("equity_legs") or [])
    assert option_legs == spec.leg_count or option_legs + equity_legs == spec.leg_count
    if summary["strategy"] in STOCK_NAMES or spec.equity_required:
        assert summary.get("stock_legs") or summary.get("equity_legs")

    assert float(IV_MISMATCH_VOL_POINTS) == 5.0
    assessment = assess_vol_regime(
        iv=summary.get("iv"),
        hv=summary.get("hv"),
        iv_rank=summary.get("iv_rank"),
    )
    assert "±5" in assessment.rule
    stored_side = _regime_side(summary.get("vol_regime"))
    assert stored_side == _regime_side(assessment.label)
    assert stored_side == _regime_side(assessment.display)
    points = assessment.iv_minus_hv_pts
    if points is not None and not assessment.tie_break:
        if points > 5:
            assert stored_side == "sell"
        elif points < -5:
            assert stored_side == "buy"
        else:
            assert stored_side == "near"

    earnings = summary.get("earnings") or {}
    for field in ("next_date", "status", "display", "date_status"):
        assert not _is_none_word(earnings.get(field))
    if ticker in ETFS:
        assert earnings.get("applicable") is False
    display = "" if earnings.get("display") is None else str(earnings.get("display"))
    date_status = str(earnings.get("date_status") or "").lower()
    estimated = date_status == "estimated" or (
        not date_status
        and earnings.get("next_date")
        and ticker not in IR_CONFIRMED
        and earnings.get("applicable") is not False
    )
    if estimated:
        assert "est." in display
    if ticker in IR_CONFIRMED and earnings.get("next_date"):
        assert "est." not in display
        assert earnings.get("next_date") == IR_CONFIRMED[ticker]["date"]
    if ticker == "GOOGL":
        assert earnings.get("next_date") == "2026-10-28"
        assert "est." in display

    assert summary.get("unmatched") == []
    assert summary.get("quote_as_of")
    assert summary.get("quote_feed")
    assert row.get("chain_feed")

    if ticker in GAMMA_NAMES:
        notes: list[str] = []
        for entry in row.get("ledger_gamma") or []:
            if entry.get("key") == GAMMA and entry.get("kind") in {None, "candidate"}:
                notes = (entry.get("inputs") or {}).get("gate_notes") or []
        if not notes and isinstance(row.get("evaluation_ledger"), list):
            for entry in row["evaluation_ledger"]:
                if entry.get("kind") == "candidate" and entry.get("key") == GAMMA:
                    notes = (entry.get("inputs") or {}).get("gate_notes") or []
        assert notes
        assert any("Earnings move history is missing" in note for note in notes)
