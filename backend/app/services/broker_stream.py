"""Alpaca trade updates for the paper account.

A fill is applied when the broker reports it. The 15-second reconcile remains
the fallback after a disconnect. This does not submit, cancel, or replace orders.
Live trading is not connected.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from loguru import logger

from app.config import Settings, get_settings
from app.services.order_queue import _apply_lock, _push_order_notices, apply_trade_update, trade_update_order


def stream_url(broker_base_url: str) -> str:
    """Trading-stream URL for an Alpaca broker host."""
    host = broker_base_url.strip().rstrip("/")
    if host.startswith("https://"):
        host = "wss://" + host[len("https://") :]
    elif host.startswith("http://"):
        host = "ws://" + host[len("http://") :]
    elif not host.startswith("ws"):
        host = "wss://" + host
    return f"{host}/stream"


def start_trade_stream(stop: asyncio.Event) -> asyncio.Task | None:
    """Listen for paper fills. Tests and a missing paper key do not open a socket."""
    if os.environ.get("PYTEST_CURRENTTEST"):
        return None
    settings = get_settings()
    if not settings.alpaca_keys_present or settings.alpaca_trading_mode != "paper":
        return None
    return asyncio.create_task(_trade_stream(stop, settings))


async def _trade_stream(stop: asyncio.Event, settings: Settings) -> None:
    import websockets

    url = stream_url(settings.resolved_broker_base_url)
    delay = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=10, ping_timeout=180) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "action": "authenticate",
                            "data": {
                                "key_id": settings.alpaca_api_key_id,
                                "secret_key": settings.alpaca_api_secret_key,
                            },
                        }
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                auth = json.loads(raw)
                if (auth.get("data") or {}).get("status") != "authorized":
                    logger.warning("trade stream was not authorized")
                    return
                await ws.send(json.dumps({"action": "listen", "data": {"streams": ["trade_updates"]}}))
                delay = 1.0
                logger.info("trade stream connected")
                while not stop.is_set():
                    try:
                        incoming = await asyncio.wait_for(ws.recv(), timeout=5)
                    except TimeoutError:
                        continue
                    await _handle_message(incoming, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("trade stream disconnected ({})", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return
            except TimeoutError:
                delay = min(delay * 2, 30.0)


async def _handle_message(raw: Any, settings: Settings) -> None:
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return
    broker = trade_update_order(message)
    if broker is None:
        return
    from app.database import SessionLocal
    from app.deps import get_adapter

    adapter = get_adapter(settings)
    async with _apply_lock(str(broker.get("id") or "")):
        async with SessionLocal() as session:
            notice = await apply_trade_update(session, broker, adapter)
            if notice is None:
                return
            await session.commit()
        await _push_order_notices([notice])
    logger.info(
        "trade update applied status={} id={}",
        broker.get("status"),
        str(broker.get("id") or "")[:8],
    )
