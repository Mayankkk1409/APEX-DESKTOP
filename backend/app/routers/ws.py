from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import get_settings
from app.security import decode_token
from app.services.live_quotes import get_live_quote
from app.ws.hub import hub

router = APIRouter()

# Live quote push. Tests shorten this so a failed refresh cannot look like a hung socket.
QUOTE_REFRESH_SECONDS = 5.0


async def _quotes_payload(symbols: list[str], settings) -> list[dict]:
    out: list[dict] = []
    for sym in symbols[:12]:
        q = await get_live_quote(sym, settings)
        out.append(q.model_dump())
    return out


async def _send_json(ws: WebSocket, payload: dict) -> bool:
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await ws.send_json(payload)
    except Exception:
        return False
    return True


@router.websocket("/ws/market")
async def market_ws(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    settings = get_settings()
    user_id = "anon"
    if token:
        try:
            payload = decode_token(settings, token)
            user_id = str(payload.get("sub") or "anon")
        except Exception:
            # Accept first so the Vite proxy gets a close frame instead of a reset (EPIPE).
            try:
                await ws.accept()
                await ws.close(code=4401)
            except Exception:
                return
            return
    await hub.connect(user_id, ws)
    last_seq_ack = 0
    subscribed: list[str] = []
    stopped = asyncio.Event()
    refresh_task: asyncio.Task | None = None

    async def refresh_loop() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), QUOTE_REFRESH_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            if stopped.is_set() or not subscribed:
                continue
            try:
                quotes = await _quotes_payload(subscribed, settings)
                if stopped.is_set():
                    return
                await hub.broadcast(user_id, {"type": "quotes", "quotes": quotes})
            except asyncio.CancelledError:
                raise
            except Exception:
                # A quote miss must not drop the fill subscription.
                continue

    try:
        if not await _send_json(
            ws,
            {"type": "hello", "seq": 0, "user_id": user_id, "note": "no drop/duplicate: seq monotonic"},
        ):
            return
        while not stopped.is_set():
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind == "ping":
                await _send_json(ws, {"type": "pong", "seq": last_seq_ack})
            elif kind == "subscribe":
                raw = data.get("symbols") or ["SPX"]
                if not isinstance(raw, list):
                    raw = ["SPX"]
                subscribed = [str(s).upper() for s in raw][:12]
                try:
                    quotes = await _quotes_payload(subscribed, settings)
                except Exception:
                    quotes = []
                await hub.broadcast(user_id, {"type": "quotes", "quotes": quotes})
                if refresh_task is None:
                    refresh_task = asyncio.create_task(refresh_loop())
            elif kind == "ack":
                try:
                    last_seq_ack = int(data.get("seq") or 0)
                except (TypeError, ValueError):
                    last_seq_ack = 0
            elif kind == "reconnect":
                # client may send last_seq; we continue incrementing — no rewind duplicates
                await _send_json(ws, {"type": "resume", "seq": last_seq_ack, "ok": True})
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    finally:
        stopped.set()
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except (asyncio.CancelledError, Exception):
                pass
        await hub.disconnect(user_id, ws)
