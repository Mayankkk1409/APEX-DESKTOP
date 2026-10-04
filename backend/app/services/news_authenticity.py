"""Shared checks so scan and dashboard sentiment never replay fabricated headlines."""

from __future__ import annotations

from typing import Any

from app.analysis.news_nlp import score_articles

# Desk-note seeds previously inserted when the news feed was down.
FAKE_SENTIMENT_HEADLINES: tuple[str, ...] = (
    "S&P 500 implied vol sits near the middle of its 52-week range",
    "Apple options: put/call volume mixed into weekly expiry",
    "Risk appetite: fear/greed-style composite near 48",
)
FAKE_SENTIMENT_SOURCES: tuple[str, ...] = (
    "APEX Research",
    "APEX Flow",
    "APEX Sentiment Worker",
)

ALPACA_NEWS_LABEL = "Alpaca News"


def no_recent_news_message(symbol: str | None) -> str:
    """Neutral empty copy after a real news query returned no articles."""
    sym = (symbol or "").strip().upper()
    if sym:
        return f"No recent news for {sym} from {ALPACA_NEWS_LABEL}."
    return f"No recent news from {ALPACA_NEWS_LABEL}."


def is_fabricated_sentiment_item(headline: str | None, source: str | None) -> bool:
    text = (headline or "").strip()
    origin = (source or "").strip()
    return text in FAKE_SENTIMENT_HEADLINES or origin in FAKE_SENTIMENT_SOURCES


def _signal(nlp: float) -> str:
    if nlp > 15:
        return "bullish"
    if nlp < -15:
        return "bearish"
    return "neutral"


def map_provider_news(raw_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map provider news rows. Headline, summary, source, and timestamp stay as returned.

    Rows missing a headline, source, or timestamp are dropped. Fabricated seed copy is dropped.
    Lexicon score is computed from the provider text; a missing score is not replaced with 50.
    """
    _mean, articles = score_articles(raw_articles)
    rows: list[dict[str, Any]] = []
    for art in articles:
        headline = (art.get("headline") or "").strip()
        source = (art.get("source") or "").strip()
        published = art.get("published_at")
        nlp = art.get("nlp_score")
        if not headline or not source or not published:
            continue
        if is_fabricated_sentiment_item(headline, source):
            continue
        if not isinstance(nlp, (int, float)):
            continue
        symbols = art.get("symbols") or []
        symbol = symbols[0] if isinstance(symbols, list) and symbols else None
        url = art.get("url")
        rows.append(
            {
                "headline": headline,
                "blurb": art.get("summary") or "",
                "source": source,
                "signal": _signal(float(nlp)),
                "score": round((float(nlp) + 100.0) / 2.0, 1),
                "score_method": "lexicon_v1",
                "published_at": published,
                "symbol": symbol if isinstance(symbol, str) else None,
                "url": url.strip() if isinstance(url, str) and url.strip() else None,
            }
        )
    return rows
