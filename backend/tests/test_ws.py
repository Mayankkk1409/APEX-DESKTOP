from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.schemas.market import Quote
from app.ws.hub import hub


async def _fake_quote(symbol: str, settings) -> Quote:  # noqa: ARG001
    return Quote(symbol=str(symbol).upper(), name=str(symbol).upper(), price=1.0, change=0.0, change_pct=0.0, status="live", source="test")


def test_ws_reconnect_no_duplicate_seq(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.ws.get_live_quote", _fake_quote)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/market") as ws1:
        hello = ws1.receive_json()
        assert hello["type"] == "hello"
        ws1.send_json({"type": "subscribe", "symbols": ["SPX", "AAPL"]})
        msg = ws1.receive_json()
        assert msg["type"] == "quotes"
        first_seq = msg["seq"]
        ws1.send_json({"type": "reconnect", "last_seq": first_seq})
        resume = ws1.receive_json()
        assert resume["type"] == "resume"
    with client.websocket_connect("/ws/market") as ws2:
        ws2.receive_json()
        ws2.send_json({"type": "subscribe", "symbols": ["SPX"]})
        msg2 = ws2.receive_json()
        assert msg2["seq"] >= first_seq
        assert msg2["type"] == "quotes"


def test_hub_exists() -> None:
    assert hub is not None


def test_bad_token_closes_cleanly() -> None:
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/market?token=not-a-jwt") as ws:
        with pytest.raises(Exception):
            ws.receive_json()


def test_quote_failure_does_not_drop_fill_socket(monkeypatch) -> None:
    import time

    monkeypatch.setattr("app.routers.ws.QUOTE_REFRESH_SECONDS", 0.05)
    calls = {"n": 0}

    async def flaky(symbol: str, settings) -> Quote:  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("quote upstream closed")
        return Quote(symbol=str(symbol).upper(), name=str(symbol).upper(), price=1.0, change=0.0, change_pct=0.0, status="live", source="test")

    monkeypatch.setattr("app.routers.ws.get_live_quote", flaky)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/market") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        ws.send_json({"type": "subscribe", "symbols": ["SPX"]})
        assert ws.receive_json()["type"] == "quotes"
        time.sleep(0.25)
        ws.send_json({"type": "ping"})
        kinds = []
        for _ in range(4):
            kinds.append(ws.receive_json()["type"])
            if "pong" in kinds:
                break
        assert "pong" in kinds
