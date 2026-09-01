"""Fetch and extract readable article HTML for the sentiment article modal."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

try:
    from readability import Document
except ImportError:  # pragma: no cover
    Document = None  # type: ignore[misc, assignment]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ENTITY = re.compile(r"&#?\w+;")
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)

# Publisher chrome that should never be shown as article body.
_JUNK_PHRASES = (
    "benzinga apis",
    "benzinga pro",
    "create a benzinga",
    "publisher returned http",
    "access denied",
    "please enable javascript",
    "sign in to continue",
    "subscribe to read",
    "cookie policy",
    "all rights reserved",
)


def _strip_html(html: str) -> str:
    text = unescape(_TAG.sub(" ", html or ""))
    return _WS.sub(" ", text).strip()


def _decode_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = unescape(str(text))
    if _ENTITY.search(cleaned):
        cleaned = unescape(cleaned)
    return _WS.sub(" ", cleaned).strip() or None


def _is_junk_body(body: str | None) -> bool:
    if not body or len(body.strip()) < 40:
        return True
    lower = body.lower()
    if any(phrase in lower for phrase in _JUNK_PHRASES):
        return True
    # Mostly navigation / link soup with little prose.
    if body.count("http") > 8 and len(body) < 600:
        return True
    return False


def _sanitize_article_html(html: str) -> str:
    """Keep readable article markup; drop scripts/styles and event handlers."""
    cleaned = _SCRIPT_STYLE.sub("", html or "")
    cleaned = re.sub(r'\s+on\w+="[^"]*"', "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+on\w+='[^']*'", "", cleaned, flags=re.I)
    return cleaned.strip()


def _browser_headers(url: str, *, profile: int = 0) -> dict[str, str]:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    profiles = (
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": origin,
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        },
        {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    return profiles[min(profile, len(profiles) - 1)]


async def _fetch_html(url: str, *, timeout: float) -> tuple[str | None, int | None, str | None]:
    last_err: str | None = None
    for profile in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers=_browser_headers(url, profile=profile),
            ) as client:
                res = await client.get(url)
                if res.status_code == 403 and profile < 2:
                    continue
                if res.status_code >= 400:
                    last_err = f"HTTP {res.status_code}"
                    if res.status_code in {403, 429} and profile < 2:
                        continue
                    return None, res.status_code, last_err
                return res.text or "", res.status_code, None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.warning("Article fetch attempt {} failed {}: {}", profile, url[:80], exc)
    return None, None, last_err


def _extract_from_html(html: str, url: str) -> dict[str, Any]:
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = _decode_text(title_match.group(1)) if title_match else None
    og_title = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html, re.I)
    if og_title:
        title = _decode_text(og_title.group(1))

    byline = None
    author_match = re.search(r'property=["\']article:author["\'][^>]*content=["\']([^"\']+)', html, re.I)
    if author_match:
        byline = _decode_text(author_match.group(1))
    if not byline:
        byline_match = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if byline_match:
            byline = _decode_text(byline_match.group(1))

    body_html: str | None = None
    body_text: str | None = None
    method = "html_strip"

    if Document is not None:
        try:
            doc = Document(html)
            title = _decode_text(doc.title()) or title
            summary_html = _sanitize_article_html(doc.summary() or "")
            body_text = _strip_html(summary_html)
            if body_text and not _is_junk_body(body_text):
                body_html = summary_html
                method = "readability_lxml"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Readability extraction failed {}: {}", url[:80], exc)

    if not body_text or _is_junk_body(body_text):
        body_text = _strip_html(html)
        body_html = None
        method = "html_strip_fallback"

    if _is_junk_body(body_text):
        return {
            "status": "error",
            "url": url,
            "title": title,
            "byline": byline,
            "error": "Publisher content could not be extracted",
        }

    excerpt = body_text[:280] + "…" if len(body_text) > 280 else body_text
    return {
        "status": "ok" if method == "readability_lxml" else "fallback",
        "url": url,
        "title": title,
        "byline": byline,
        "body": body_text,
        "body_html": body_html,
        "excerpt": excerpt,
        "method": method,
    }


def _fallback_from_feed_text(text: str | None, url: str) -> dict[str, Any] | None:
    """Use Alpaca/news-feed body when publisher fetch is blocked."""
    body = _decode_text(text)
    if not body:
        return None
    if _TAG.search(body):
        body = _strip_html(body)
    if _is_junk_body(body):
        return None
    excerpt = body[:280] + "…" if len(body) > 280 else body
    return {
        "status": "fallback",
        "url": url,
        "body": body,
        "body_html": None,
        "excerpt": excerpt,
        "method": "news_feed",
    }


async def fetch_article_content(
    url: str,
    *,
    fallback_text: str | None = None,
    timeout: float = 14.0,
) -> dict[str, Any]:
    """Fetch article HTML and extract headline/byline/body via readability-lxml."""
    raw = (url or "").strip()
    if not raw:
        return {"status": "error", "url": url, "error": "URL is required"}
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "error", "url": raw, "error": "Invalid article URL"}

    html, status_code, fetch_err = await _fetch_html(raw, timeout=timeout)
    if not html:
        feed = _fallback_from_feed_text(fallback_text, raw)
        if feed:
            return feed
        return {
            "status": "error",
            "url": raw,
            "error": "Publisher content could not be extracted",
            "http_status": status_code,
            "detail": fetch_err,
        }

    extracted = _extract_from_html(html, raw)
    if extracted.get("status") == "error":
        feed = _fallback_from_feed_text(fallback_text, raw)
        if feed:
            if extracted.get("title"):
                feed["title"] = extracted["title"]
            if extracted.get("byline"):
                feed["byline"] = extracted["byline"]
            return feed
    return extracted
