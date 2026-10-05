"""Replay of the 50-row QA sheet against captured market data.

Rows whose capture failed are skipped with that reason. The fixture is the
provider payload summary from the capture script. It is not a synthetic chain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.strategies.registry import STRATEGY_REGISTRY

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "change12_qa_replay.json"
GAMMA = "Gamma Trampoline™"
GAMMA_NAMES = ("JPM", "GS", "C", "JNJ", "UNH", "BAC", "WFC", "MS", "BLK", "PLD")
STOCK_NAMES = ("Married Put", "Covered Call", "Collar", "Protective Collar")


def _rows() -> list[dict]:
    payload = json.loads(FIXTURE.read_text())
    return list(payload["rows"])


def _spec_by_name() -> dict:
    return {spec.display_name: spec for spec in STRATEGY_REGISTRY.values()}


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["ticker"])
def test_qa_replay_row(row: dict) -> None:
    if row.get("error"):
        pytest.skip(f"{row['ticker']} {row['expiry']}: {row['error']}")
    summary = row["summary"]
    status = summary["status"]
    eligible = bool(summary["eligible"])
    assert not (status == "NOT EXECUTABLE" and eligible)

    spec = _spec_by_name().get(summary["strategy"])
    assert spec is not None
    option_legs = int(summary["leg_count"])
    equity_legs = len(summary.get("equity_legs") or [])
    assert option_legs == spec.leg_count or option_legs + equity_legs == spec.leg_count
    if summary["strategy"] in STOCK_NAMES or spec.equity_required:
        assert summary.get("stock_legs") or summary.get("equity_legs")

    earnings = summary["earnings"]
    assert earnings.get("next_date") != "none"
    assert str(earnings.get("status") or "").lower() != "none"
    if row["ticker"] in {"SPY", "QQQ"}:
        assert earnings.get("applicable") is False
    if row["ticker"] == "GOOGL":
        assert earnings.get("next_date") == "2026-10-28"
        assert "est." in str(earnings.get("display") or "")

    assert summary.get("unmatched") == []
    assert summary.get("quote_as_of")
    assert summary.get("quote_feed")
    assert row.get("chain_feed")

    if row["ticker"] in GAMMA_NAMES:
        notes = []
        for entry in row.get("ledger_gamma") or []:
            if entry.get("key") == GAMMA:
                notes = (entry.get("inputs") or {}).get("gate_notes") or []
        assert notes
        assert any("Earnings move history is missing" in note for note in notes)
