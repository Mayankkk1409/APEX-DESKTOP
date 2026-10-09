"""Evaluation ledger, evidence provenance, and the debug read route."""

from __future__ import annotations

from dataclasses import fields

import pytest
from httpx import AsyncClient

from app.contracts import LedgerEntry, ledger
from app.services.evidence_ledger import (
    evaluation,
    get,
    record,
    record_candidate,
    record_card_value,
    record_chain_flags,
    record_gate,
    record_rank,
    record_score,
    reset_ledger,
)

@pytest.fixture(autouse=True)
def _clean_ledger() -> None:
    reset_ledger()
    yield
    reset_ledger()


def test_ledger_entry_fields_stay_frozen() -> None:
    assert [item.name for item in fields(LedgerEntry)] == [
        "scanId",
        "kind",
        "key",
        "value",
        "inputs",
        "source",
        "feed",
        "timestamp",
        "fn",
    ]
    ledger.record(
        LedgerEntry(
            scanId="frozen",
            kind="value",
            key="iv",
            value=1,
            inputs={"iv": 1},
            source="alpaca",
            feed="indicative",
            timestamp="2026-10-05T14:00:00Z",
            fn="quote_snapshot",
        )
    )
    assert ledger.get("frozen") == []


def test_scan_stores_gates_candidates_scores_and_rank() -> None:
    scan_id = "scan-eval"
    record_gate(
        scan_id,
        "bull_put_spread_credit",
        "spread",
        0.08,
        0.10,
        True,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="check_spread",
    )
    record_gate(
        scan_id,
        "gamma_trampoline",
        "term_structure",
        1.1,
        1.25,
        False,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="check_inversion",
    )
    record_candidate(
        scan_id,
        "bull_put_spread_credit",
        "put-vertical",
        {"symbol": "AAPL", "strike": 220, "side": "put"},
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="build_candidate",
    )
    record_score(
        scan_id,
        "bull_put_spread_credit",
        "technicals",
        18.4,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="score_technicals",
    )
    record_rank(
        scan_id,
        "bull_put_spread_credit",
        1,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="select_best",
    )
    record_rank(
        scan_id,
        "gamma_trampoline",
        4,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="select_best",
    )

    view = evaluation(scan_id)
    bull = view["strategies"]["bull_put_spread_credit"]
    gamma = view["strategies"]["gamma_trampoline"]
    assert bull["rank"] == 1
    assert bull["gates"][0]["passed"] is True
    assert bull["gates"][0]["measured"] == 0.08
    assert bull["gates"][0]["threshold"] == 0.10
    assert bull["scores"][0]["value"] == 18.4
    assert bull["candidates"][0]["value"]["symbol"] == "AAPL"
    assert gamma["gates"][0]["passed"] is False
    assert gamma["gates"][0]["measured"] == 1.1
    assert gamma["gates"][0]["threshold"] == 1.25
    assert gamma["rank"] == 4
    assert list(view["strategies"])[0] == "bull_put_spread_credit"
    other = get("scan-other")
    assert other == []
    assert len(get(scan_id)) == 6


def test_card_values_keep_provenance_and_scans_stay_separate() -> None:
    first = record_card_value(
        "scan-a",
        "iv",
        30.31,
        inputs={"atm_iv": 0.3031},
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="chain_summary",
    )
    record_card_value(
        "scan-b",
        "hv",
        20.38,
        inputs={"window": 30},
        source="alpaca",
        feed="opra",
        timestamp="2026-10-05T14:05:00Z",
        fn="realized_vol",
    )
    rows = get("scan-a")
    assert len(rows) == 1
    assert rows[0].key == "iv"
    for entry in (first, rows[0]):
        assert entry.inputs
        assert entry.source == "alpaca"
        assert entry.feed == "indicative"
        assert entry.timestamp == "2026-10-05T14:00:00Z"
        assert entry.fn == "chain_summary"
    assert get("scan-b")[0].key == "hv"


def test_card_value_without_provenance_is_rejected() -> None:
    with pytest.raises(ValueError, match="inputs"):
        record_card_value(
            "scan-a",
            "iv",
            30.31,
            inputs={},
            source="alpaca",
            feed="indicative",
            timestamp="2026-10-05T14:00:00Z",
            fn="chain_summary",
        )
    with pytest.raises(ValueError, match="timestamp"):
        record(
            LedgerEntry(
                scanId="scan-a",
                kind="value",
                key="iv",
                value=30.31,
                inputs={"atm_iv": 0.3031},
                source="alpaca",
                feed=None,
                timestamp="",
                fn="chain_summary",
            )
        )
    assert get("scan-a") == []


def test_chain_flags_are_copied_and_not_recomputed() -> None:
    flag = {
        "code": "crossed_market",
        "symbol": "AAPL261030C00100000",
        "strike": 100.0,
        "side": "call",
        "value": 3.0,
        "threshold": 1.0,
        "detail": "bid 3.0 is greater than ask 1.0",
        "feed": "indicative",
        "source": "alpaca",
        "timestamp": "2026-10-05T14:00:00Z",
    }
    flags = [
        flag,
        {
            "code": "inverted_put_skew",
            "symbol": "AAPL261030P00090000",
            "strike": 90.0,
            "value": 0.274,
            "threshold": 0.3031,
            "feed": "indicative",
            "source": "alpaca",
            "timestamp": "2026-10-05T14:00:00Z",
        },
        {
            "code": "iv_outside_chain_range",
            "symbol": "AAPL261030C00110000",
            "strike": 110.0,
            "side": "call",
            "value": 0.9,
            "threshold": [0.2, 0.4],
            "feed": "indicative",
            "source": "alpaca",
            "timestamp": "2026-10-05T14:00:00Z",
        },
        {"code": "not_a_flag", "value": 1, "threshold": 2, "source": "alpaca", "timestamp": "2026-10-05T14:00:00Z"},
    ]
    payload = {"ledger_flags": flags, "summary": {"ledger_flags": flags}}
    recorded = record_chain_flags("scan-flags", payload)
    assert [row.key for row in recorded] == [
        "crossed_market",
        "inverted_put_skew",
        "iv_outside_chain_range",
    ]
    crossed = recorded[0]
    assert crossed.value["measured"] == 3.0
    assert crossed.value["threshold"] == 1.0
    assert crossed.source == "alpaca"
    assert crossed.feed == "indicative"
    assert crossed.timestamp == "2026-10-05T14:00:00Z"
    assert crossed.fn == "chain_quote_flags"
    assert crossed.inputs["symbol"] == flag["symbol"]
    assert record_chain_flags(
        "scan-bare",
        {"bid": 5.0, "ask": 1.0, "contracts": [{"bid": 5.0, "ask": 1.0, "iv": 0.9, "side": "call", "strike": 100}]},
    ) == []
    assert get("scan-bare") == []
    view = evaluation("scan-flags")
    assert {item["key"] for item in view["flags"]} == {
        "crossed_market",
        "inverted_put_skew",
        "iv_outside_chain_range",
    }


async def _signup(client: AsyncClient) -> str:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Paper Trader",
            "username": "ledger1",
            "email": "ledger1@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text
    await client.post("/auth/login", json={"username": "ledger1", "password": "ApexDesk!23"})
    otp = await client.post("/auth/otp/request", json={"username": "ledger1"})
    assert otp.status_code == 200, otp.text
    verify = await client.post("/auth/otp/verify", json={"username": "ledger1", "code": otp.json()["code"]})
    assert verify.status_code == 200, verify.text
    return verify.json()["access_token"]


@pytest.mark.asyncio
async def test_debug_route_returns_the_scan_ledger(client: AsyncClient) -> None:
    denied = await client.get("/api/ledger/scan-debug")
    assert denied.status_code == 401
    token = await _signup(client)
    record_gate(
        "scan-debug",
        "bull_put_spread_credit",
        "spread",
        0.08,
        0.10,
        True,
        source="alpaca",
        feed="indicative",
        timestamp="2026-10-05T14:00:00Z",
        fn="check_spread",
    )
    res = await client.get("/api/ledger/scan-debug", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scanId"] == "scan-debug"
    assert body["entries"][0]["kind"] == "gate"
    assert body["entries"][0]["inputs"]["measured"] == 0.08
    gate = body["evaluation"]["strategies"]["bull_put_spread_credit"]["gates"][0]
    assert gate["passed"] is True
    assert gate["measured"] == 0.08
    assert gate["threshold"] == 0.10
    assert gate["source"] == "alpaca"
    assert gate["fn"] == "check_spread"
