from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.security import decode_token
from app.services.live_quotes import get_live_quote
from app.ws.hub import hub

router = APIRouter()


async def _quotes_payload(symbols: list[str], settings) -> list[dict]:
    out: list[dict] = []
    for sym in symbols[:12]:
        q = await get_live_quote(sym, settings)
        out.append(q.model_dump())
    return out


@router.websocket("/ws/market")
async def market_ws(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    settings = get_settings()
    user_id = "anon"
    if token:
        try:
            payload = decode_token(settings, token)
            user_id = payload.get("sub", "anon")
        except Exception:
            await ws.close(code=4401)
            return
    await hub.connect(user_id, ws)
    last_seq_ack = 0
    subscribed: list[str] = []
    refresh_task: asyncio.Task | None = None

    async def refresh_loop() -> None:
        while True:
            await asyncio.sleep(5)
            if not subscribed:
                continue
            quotes = await _quotes_payload(subscribed, settings)
            await hub.broadcast(user_id, {"type": "quotes", "quotes": quotes})

    try:
        await ws.send_json({"type": "hello", "seq": 0, "user_id": user_id, "note": "no drop/duplicate: seq monotonic"})
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind == "ping":
                await ws.send_json({"type": "pong", "seq": last_seq_ack})
            elif kind == "subscribe":
                subscribed = [str(s).upper() for s in (data.get("symbols") or ["SPX"])]
                quotes = await _quotes_payload(subscribed, settings)
                await hub.broadcast(user_id, {"type": "quotes", "quotes": quotes})
                if refresh_task is None:
                    refresh_task = asyncio.create_task(refresh_loop())
            elif kind == "ack":
                last_seq_ack = int(data.get("seq") or 0)
            elif kind == "reconnect":
                # client may send last_seq; we continue incrementing — no rewind duplicates
                await ws.send_json({"type": "resume", "seq": last_seq_ack, "ok": True})
    except WebSocketDisconnect:
        await hub.disconnect(user_id, ws)
    except Exception:
        await hub.disconnect(user_id, ws)
    finally:
        if refresh_task:
            refresh_task.cancel()
