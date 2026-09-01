from __future__ import annotations

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
