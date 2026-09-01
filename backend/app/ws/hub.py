from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._clients: dict[str, list[WebSocket]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients[user_id].append(ws)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._clients[user_id]:
                self._clients[user_id].remove(ws)

    async def broadcast(self, user_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._seq[user_id] += 1
            seq = self._seq[user_id]
            targets = list(self._clients.get(user_id, []))
        message = {"seq": seq, **payload}
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                for ws in stale:
                    if ws in self._clients[user_id]:
                        self._clients[user_id].remove(ws)


hub = Hub()
