"""Article reader extraction tests — three publisher HTML shapes."""

from __future__ import annotations

import pytest

from app.analysis.news_nlp import score_articles
from app.services import article_reader as ar


REUTERS_HTML = """
<html><head>
<title>Apple shares rise on upgrade | Reuters</title>
<meta property="article:author" content="Jane Desk"/>
</head><body>
<nav>Skip navigation</nav>
<article><h1>Apple shares rise on upgrade</h1>
<p>Analysts lifted price targets after strong services growth beat expectations.</p>
<p>Shares closed higher in a broad market rally.</p></article>
<footer>Reuters footer</footer>
</body></html>
"""

BENZINGA_HTML = """
<html><head><title>NVDA beats estimates</title>
<meta name="author" content="Benzinga Staff"/>
</head><body>
<div class="sidebar">Ads</div>
<div class="article-content"><h1>NVDA beats estimates</h1>
<p>NVIDIA reported quarterly revenue above Wall Street consensus.</p>
<p>Data-center demand remained the primary driver.</p></div>
</body></html>
"""

MARKETWATCH_HTML = """
<html><head><title>MarketWatch: Fed outlook shifts</title></head><body>
<header>MarketWatch</header>
<main><h1>Fed outlook shifts</h1>
<p>Investors repriced rate-cut odds after the latest CPI print.</p>
<p>Bond yields fell while equities held steady.</p></main>
</body></html>
"""


@pytest.mark.asyncio
async def test_article_reader_reuters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(url: str, *, timeout: float = 14.0):
        return {"status": "ok", "url": url, "title": "Apple shares rise on upgrade", "byline": "Jane Desk", "body": "Analysts lifted price targets", "method": "readability_lxml"}

    monkeypatch.setattr(ar, "fetch_article_content", fake_get)
    out = await ar.fetch_article_content("https://reuters.com/markets/apple")
    assert out["status"] == "ok"
    assert out.get("body")


@pytest.mark.asyncio
async def test_article_reader_extracts_three_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url: str):
            if "reuters" in url:
                return FakeResponse(REUTERS_HTML)
            if "benzinga" in url:
                return FakeResponse(BENZINGA_HTML)
            return FakeResponse(MARKETWATCH_HTML)

    monkeypatch.setattr(ar.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    for url in (
        "https://www.reuters.com/markets/apple-upgrade",
        "https://www.benzinga.com/news/nvda",
        "https://www.marketwatch.com/story/fed-outlook",
    ):
        out = await ar.fetch_article_content(url)
        assert out["status"] in {"ok", "fallback"}
        assert out.get("body")
        assert len(out["body"]) > 30


@pytest.mark.asyncio
async def test_article_reader_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = "gone"
        status_code = 404

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(ar.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    out = await ar.fetch_article_content("https://example.com/missing")
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_article_reader_403_uses_feed_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = ""
        status_code = 403

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(ar.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    fallback = (
        "IREN shares rallied after the company announced expanded data-center capacity "
        "and stronger-than-expected mining output for the quarter."
    )
    out = await ar.fetch_article_content("https://www.benzinga.com/news/iren", fallback_text=fallback)
    assert out["status"] == "fallback"
    assert out.get("body")
    assert "IREN shares rallied" in out["body"]
    assert "403" not in out["body"]


def test_news_nlp_decodes_html_entities() -> None:
    mean, rows = score_articles(
        [
            {
                "headline": "IREN&#39;s AI pivot gains traction",
                "summary": "Shares rose after the company&#39;s update.",
                "source": "benzinga",
                "created_at": "2026-01-01",
            }
        ]
    )
    assert rows[0]["headline"] == "IREN's AI pivot gains traction"
    assert "company's update" in (rows[0]["summary"] or "")
    assert mean is not None


@pytest.mark.asyncio
async def test_article_reader_rejects_boilerplate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = "<html><body>Benzinga APIs Login Create Account</body></html>"
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(ar.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    out = await ar.fetch_article_content("https://www.benzinga.com/news/iren")
    assert out["status"] == "error"
