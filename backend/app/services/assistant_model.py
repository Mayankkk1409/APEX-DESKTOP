"""Call the local Ollama chat API. No cloud provider and no screen payload."""

from __future__ import annotations

import httpx
from loguru import logger

from app.config import Settings

_SYSTEM = (
    "You are APEX AI inside the APEX paper-trading terminal. "
    "Answer only a general question about trading words, how stocks and options work, "
    "bid and ask, P&L, indicators, or where an existing screen lives "
    "(Portfolio, Settings, Deep Scan, or the chart desk). "
    "Keep the answer short. Do not give personalized advice, trade recommendations, "
    "or price targets. Do not claim you can see the user's screen, positions, or orders. "
    "Do not place an order or describe steps that submit one. "
    "If the question needs the user's account, say that is outside this answer."
)


class AssistantProviderError(Exception):
    """Ollama did not return an answer."""


async def complete_basic_answer(settings: Settings, message: str) -> str:
    base = settings.apex_ai_base_url.strip().rstrip("/")
    model = settings.apex_ai_model.strip()
    if not base or not model:
        logger.warning("assistant ollama is missing a base URL or model name")
        raise AssistantProviderError()
    url = base + "/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": message},
        ],
        "options": {"temperature": 0.2, "num_predict": 400},
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("assistant ollama request failed ({})", type(exc).__name__)
        raise AssistantProviderError() from exc
    if response.status_code >= 400:
        logger.warning("assistant ollama status {}", response.status_code)
        raise AssistantProviderError()
    try:
        body = response.json()
        text = body["message"]["content"]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("assistant ollama payload was not a chat message")
        raise AssistantProviderError() from exc
    if not isinstance(text, str) or not text.strip():
        logger.warning("assistant ollama returned an empty message")
        raise AssistantProviderError()
    return text.strip()[:4000]
