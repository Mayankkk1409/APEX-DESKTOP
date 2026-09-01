"""Lightweight financial-headline NLP for Deep Scan sentiment (§7.1).

Scores are lexicon-based over headline + summary text. This is not a vendor
sentiment API — methodology is labeled on every payload so the UI can disclose it.
Missing text → ``None`` (never a fabricated 0).
"""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable

# Word stems / phrases with signed polarity. Kept short and finance-specific so
# generic prose does not dominate. Magnitudes are relative, not calibrated alphas.
_BULLISH: dict[str, float] = {
    "beat": 1.4,
    "beats": 1.4,
    "surge": 1.6,
    "surges": 1.6,
    "rally": 1.4,
    "rallies": 1.4,
    "soar": 1.6,
    "soars": 1.6,
    "upgrade": 1.5,
    "upgrades": 1.5,
    "upgraded": 1.5,
    "outperform": 1.3,
    "outperforms": 1.3,
    "bullish": 1.5,
    "record": 1.0,
    "growth": 0.9,
    "profit": 0.8,
    "profits": 0.8,
    "strong": 0.7,
    "raised": 1.1,
    "raises": 1.1,
    "buyback": 1.0,
    "approval": 0.9,
    "approved": 0.9,
    "partnership": 0.7,
    "breakthrough": 1.2,
    "optimistic": 1.0,
    "accelerate": 0.8,
    "accelerates": 0.8,
}

_BEARISH: dict[str, float] = {
    "miss": 1.4,
    "misses": 1.4,
    "missed": 1.4,
    "plunge": 1.6,
    "plunges": 1.6,
    "slump": 1.4,
    "slumps": 1.4,
    "crash": 1.7,
    "downgrade": 1.5,
    "downgrades": 1.5,
    "downgraded": 1.5,
    "underperform": 1.3,
    "bearish": 1.5,
    "lawsuit": 1.1,
    "probe": 1.0,
    "investigation": 1.1,
    "cut": 0.9,
    "cuts": 0.9,
    "layoff": 1.2,
    "layoffs": 1.2,
    "weak": 0.8,
    "warning": 1.1,
    "warns": 1.1,
    "fraud": 1.6,
    "default": 1.5,
    "bankruptcy": 1.8,
    "recall": 1.1,
    "delay": 0.8,
    "delayed": 0.8,
    "decline": 0.9,
    "declines": 0.9,
    "fall": 0.7,
    "falls": 0.7,
    "fear": 1.0,
    "concern": 0.7,
    "concerns": 0.7,
}

_TOKEN = re.compile(r"[a-z][a-z'-]{1,24}")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean_feed_text(text: str | None, *, max_len: int = 12000) -> str | None:
    """Decode entities and strip markup from Alpaca/news-feed text."""
    if not text or not str(text).strip():
        return None
    cleaned = unescape(str(text))
    if _TAG.search(cleaned):
        cleaned = _TAG.sub(" ", cleaned)
    cleaned = _WS.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def score_text(text: str | None) -> float | None:
    """Return a signed score in ``[-100, +100]`` or ``None`` when there is no usable text."""
    if not text or not str(text).strip():
        return None
    tokens = _TOKEN.findall(str(text).lower())
    if not tokens:
        return None
    raw = 0.0
    hits = 0
    for tok in tokens:
        if tok in _BULLISH:
            raw += _BULLISH[tok]
            hits += 1
        elif tok in _BEARISH:
            raw -= _BEARISH[tok]
            hits += 1
    if hits == 0:
        return 0.0  # readable text with no lexicon hits → neutral, not missing
    # Soft saturate so a few strong words reach the extremes without clipping early.
    scaled = max(-100.0, min(100.0, (raw / max(hits, 1)) * 55.0))
    return round(scaled, 1)


def score_articles(articles: Iterable[dict]) -> tuple[float | None, list[dict]]:
    """Score each article and return (mean signed score, enriched article rows)."""
    rows: list[dict] = []
    scores: list[float] = []
    for art in articles:
        headline = _clean_feed_text(art.get("headline"), max_len=500) or ""
        raw_summary = art.get("summary") or art.get("content") or ""
        summary = _clean_feed_text(raw_summary, max_len=420) or ""
        raw_content = _clean_feed_text(art.get("content"), max_len=12000)
        blob = f"{headline}. {summary or raw_content or ''}".strip()
        scored = score_text(blob)
        row = {
            "headline": headline or None,
            "summary": summary or None,
            "content": raw_content,
            "source": art.get("source") or None,
            "author": art.get("author") or None,
            "url": art.get("url") or None,
            "published_at": art.get("created_at") or art.get("updated_at") or art.get("published_at"),
            "symbols": art.get("symbols") or [],
            "nlp_score": scored,
            "nlp_method": "lexicon_v1",
        }
        rows.append(row)
        if scored is not None and headline:
            scores.append(scored)
    if not scores:
        return None, rows
    return round(sum(scores) / len(scores), 1), rows
