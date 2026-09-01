from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["ENCRYPTION_KEY"] = "test-encryption-key-32-bytes!!"
os.environ["SNAPTRADE_CLIENT_ID"] = "test-client"
os.environ["SNAPTRADE_CONSUMER_KEY"] = "test-consumer-key"

from app.main import create_app
from app.services import snaptrade as st


@pytest.fixture
def app():
    st._client.cache_clear()
    return create_app()


@pytest.mark.asyncio
async def test_brokerage_routes_registered(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        openapi = await client.get("/openapi.json")
    paths = openapi.json()["paths"]
    assert "/api/brokerage/register-user" in paths
    assert "/api/brokerage/connection-portal-url" in paths
    assert "/api/brokerage/callback" in paths
    assert "/api/brokerage/webhook" in paths
    assert "/api/brokerage/accounts" in paths
    assert "/api/brokerage/sync" in paths
    assert "/api/brokerage/accounts/{account_id}/balance" in paths
    assert "/api/brokerage/accounts/{account_id}/positions" in paths
    assert "/api/brokerage/accounts/{account_id}/equity-history" in paths
    assert "/api/brokerage/accounts/{account_id}/orders" in paths
    assert "/api/brokerage/accounts/{account_id}" in paths


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client) -> None:
    payload = {"eventType": "ACCOUNT_HOLDINGS_UPDATED", "userId": "apex-user"}
    body = json.dumps(payload).encode("utf-8")
    res = await client.post("/api/brokerage/webhook", content=body, headers={"Signature": "bad"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature(client) -> None:
    payload = {
        "eventType": "ACCOUNT_HOLDINGS_UPDATED",
        "eventTimestamp": datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(b"test-consumer-key", body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    with patch("app.routers.brokerage.sync_connection", new=AsyncMock()):
        res = await client.post("/api/brokerage/webhook", content=body, headers={"Signature": signature})
    assert res.status_code == 200
