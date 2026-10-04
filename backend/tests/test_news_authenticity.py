"""Live news, sentiment, and event dates must come from provider payloads."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.analysis.composite_score import compute_apex_composite_score
from app.config import Settings
from app.database import Base
from app.models.trading import SentimentItem
from app.services import sentiment_layer as sl
from app.services.catalyst_calendar import event_date_from_row
from app.services.fundamentals_layer import announcement_date
from app.services.news_authenticity import (
    FAKE_SENTIMENT_HEADLINES,
    map_provider_news,
)
from app.workers.sentiment import scrape_sentiment

PROVIDER_ARTICLE = {
    "headline": "Microsoft raises dividend after record profit",
    "summary": "Board approved a higher payout.",
    "source": "benzinga",
    "created_at": "2026-10-01T14:30:00Z",
    "symbols": ["MSFT"],
    "url": "https://example.com/msft",
}


def test_provider_news_mapped_unchanged_and_seed_headlines_absent() -> None:
    rows = map_provider_news([PROVIDER_ARTICLE])
    assert len(rows) == 1
    assert rows[0]["headline"] == PROVIDER_ARTICLE["headline"]
    assert rows[0]["blurb"] == PROVIDER_ARTICLE["summary"]
    assert rows[0]["source"] == PROVIDER_ARTICLE["source"]
    assert rows[0]["published_at"] == PROVIDER_ARTICLE["created_at"]
    assert rows[0]["symbol"] == "MSFT"
    assert rows[0]["url"] == PROVIDER_ARTICLE["url"]
    assert rows[0]["score_method"] == "lexicon_v1"
    assert rows[0]["score"] != 50
    blob = " ".join(row["headline"] for row in rows)
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in blob


def test_seed_headlines_are_not_mapped_even_if_present_in_payload() -> None:
    raw = [
        {
            "headline": FAKE_SENTIMENT_HEADLINES[0],
            "summary": "Desk note: IVR moderate.",
            "source": "APEX Research",
            "created_at": "2026-10-01T14:30:00Z",
        }
    ]
    assert map_provider_news(raw) == []


def test_earnings_date_comes_from_announcement_payload() -> None:
    assert announcement_date("Earnings announcement* for AAPL: Oct 29, 2026") == date(2026, 10, 29)
    assert announcement_date(None) is None
    assert announcement_date("Earnings date not announced") is None


def test_event_date_prefers_provider_field() -> None:
    queried = date(2026, 10, 1)
    assert event_date_from_row({"date": "2026-11-02", "symbol": "ACN"}, queried) == "2026-11-02"
    assert event_date_from_row({"symbol": "ACN", "time": "time-not-supplied"}, queried) == "2026-10-01"


def test_missing_sentiment_is_not_a_neutral_50() -> None:
    shared = dict(
        technical_score=80.0,
        volatility_score=75.0,
        options_score=70.0,
        fundamental_score=60.0,
    )
    invented = compute_apex_composite_score(**shared, sentiment_score=50.0)
    omitted = compute_apex_composite_score(**shared, sentiment_score=None)
    assert omitted.sentiment is None
    assert omitted.weights_applied["sentiment"] == 0.0
    assert omitted.composite != invented.composite
    assert omitted.to_api_dict()["components"][3]["score"] is None


@pytest.mark.asyncio
async def test_sentiment_layer_keeps_provider_article(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_news(symbol: str, settings: Settings, *, limit: int = 20):
        return [PROVIDER_ARTICLE], None

    monkeypatch.setattr(sl, "_fetch_alpaca_news", fake_news)
    out = await sl.build_sentiment_layer("MSFT", Settings(), chain=None, fundamentals=None)
    article = out["components"]["news"]["articles"][0]
    assert article["headline"] == PROVIDER_ARTICLE["headline"]
    assert article["summary"] == PROVIDER_ARTICLE["summary"]
    assert article["source"] == "benzinga"
    assert article["published_at"] == PROVIDER_ARTICLE["created_at"]
    assert article["url"] == PROVIDER_ARTICLE["url"]
    assert out["components"]["news"]["source"] == "Alpaca News"
    assert out["components"]["news"]["as_of"]
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in out["narrative"]


@pytest.mark.asyncio
async def test_sentiment_layer_unavailable_does_not_invent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_news(symbol: str, settings: Settings, *, limit: int = 20):
        return [], "News feed unavailable — market data credentials not configured"

    monkeypatch.setattr(sl, "_fetch_alpaca_news", fake_news)
    out = await sl.build_sentiment_layer("MSFT", Settings(), chain=None, fundamentals=None)
    assert out["components"]["news"]["articles"] == []
    assert out["components"]["news"]["error"] == "News feed unavailable — market data credentials not configured"
    assert out["score"] is None
    assert out["score_0_100"] is None
    assert out["band"] == "Unavailable"
    blob = out["narrative"]
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in blob
    assert "50" not in str(out["score_0_100"])


@pytest.mark.asyncio
async def test_dashboard_sentiment_does_not_return_seed_copy(client: AsyncClient) -> None:
    res = await client.get("/sentiment")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["fear_greed"] is None
    assert body["status"] == "unavailable"
    assert "credentials not configured" in body["caveat"]
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in res.text


@pytest.mark.asyncio
async def test_scrape_purges_seed_and_stores_provider_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def empty_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        return [], "News feed unavailable — market data credentials not configured"

    async def live_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        return [PROVIDER_ARTICLE], None

    async with Session() as session:
        session.add(
            SentimentItem(
                symbol="SPX",
                headline=FAKE_SENTIMENT_HEADLINES[0],
                blurb="Desk note: IVR moderate.",
                source="APEX Research",
                signal="neutral",
                score=51.0,
                published_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        monkeypatch.setattr("app.workers.sentiment.fetch_alpaca_news", empty_feed)
        stored = await scrape_sentiment(session)
        assert stored == 0
        remaining = (await session.scalars(select(SentimentItem))).all()
        assert remaining == []

        monkeypatch.setattr("app.workers.sentiment.fetch_alpaca_news", live_feed)
        stored = await scrape_sentiment(session)
        assert stored == 1
        row = (await session.scalars(select(SentimentItem))).one()
        assert row.headline == PROVIDER_ARTICLE["headline"]
        assert row.blurb == PROVIDER_ARTICLE["summary"]
        assert row.source == "benzinga"
        assert row.published_at.isoformat().startswith("2026-10-01T14:30:00")
        for fake in FAKE_SENTIMENT_HEADLINES:
            assert fake != row.headline

    await engine.dispose()


FORBIDDEN_EMPTY = "No live Alpaca headlines are stored for this desk yet."


def test_forbidden_empty_copy_is_not_in_the_news_route() -> None:
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("app/routers/watchlist.py").read_text()
    assert FORBIDDEN_EMPTY not in source
    assert "this desk" not in source


@pytest.mark.asyncio
async def test_symbol_with_news_maps_source_timestamp_and_link(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def live_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        assert symbol == "AAPL"
        return [dict(PROVIDER_ARTICLE, symbols=["AAPL"])], None

    monkeypatch.setattr("app.routers.watchlist.fetch_alpaca_news", live_feed)
    res = await client.get("/sentiment", params={"symbol": "AAPL"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "live"
    assert FORBIDDEN_EMPTY not in res.text
    item = body["items"][0]
    assert item["headline"] == PROVIDER_ARTICLE["headline"]
    assert item["source"] == "benzinga"
    assert item["published_at"] == PROVIDER_ARTICLE["created_at"]
    assert item["url"] == PROVIDER_ARTICLE["url"]
    assert item["score_method"] == "lexicon_v1"
    assert item["score"] != 50


@pytest.mark.asyncio
async def test_symbol_with_no_news_uses_neutral_empty_copy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def empty_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        assert symbol == "AAPL"
        return [], None

    monkeypatch.setattr("app.routers.watchlist.fetch_alpaca_news", empty_feed)
    res = await client.get("/sentiment", params={"symbol": "aapl"})
    body = res.json()
    assert body["items"] == []
    assert body["status"] == "empty"
    assert body["caveat"] == "No recent news for AAPL from Alpaca News."
    assert "desk" not in body["caveat"]
    assert "stored" not in body["caveat"]
    assert FORBIDDEN_EMPTY not in res.text


@pytest.mark.asyncio
async def test_provider_failure_returns_reason_and_no_headlines(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        return [], "News feed HTTP 503"

    monkeypatch.setattr("app.routers.watchlist.fetch_alpaca_news", failed)
    res = await client.get("/sentiment", params={"symbol": "AAPL"})
    body = res.json()
    assert body["items"] == []
    assert body["status"] == "unavailable"
    assert body["caveat"] == "News feed HTTP 503"
    assert body["fear_greed"] is None
    assert FORBIDDEN_EMPTY not in res.text
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in res.text


@pytest.mark.asyncio
async def test_invalid_symbol_does_not_invent_headlines(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def empty_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        assert symbol == "ZZZZNOTREAL"
        return [], None

    monkeypatch.setattr("app.routers.watchlist.fetch_alpaca_news", empty_feed)
    res = await client.get("/sentiment", params={"symbol": "zzzznotreal"})
    body = res.json()
    assert body["items"] == []
    assert body["caveat"] == "No recent news for ZZZZNOTREAL from Alpaca News."
    assert FORBIDDEN_EMPTY not in res.text


@pytest.mark.asyncio
async def test_weekend_empty_feed_does_not_invent_headlines(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed session still queries the provider. An empty payload stays empty."""

    async def weekend_feed(settings: Settings, *, symbol: str | None = None, limit: int = 20):
        assert symbol == "SPY"
        return [], None

    monkeypatch.setattr("app.routers.watchlist.fetch_alpaca_news", weekend_feed)
    res = await client.get("/sentiment", params={"symbol": "SPY"})
    body = res.json()
    assert body["status"] == "empty"
    assert body["items"] == []
    assert body["caveat"] == "No recent news for SPY from Alpaca News."
    assert body["fear_greed"] is None
    for fake in FAKE_SENTIMENT_HEADLINES:
        assert fake not in res.text


@pytest.mark.asyncio
async def test_sentiment_layer_empty_query_names_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_feed(symbol: str, settings: Settings, *, limit: int = 20):
        return [], None

    monkeypatch.setattr(sl, "_fetch_alpaca_news", empty_feed)
    out = await sl.build_sentiment_layer("AAPL", Settings(), chain=None, fundamentals=None)
    assert out["components"]["news"]["status"] == "empty"
    assert out["components"]["news"]["articles"] == []
    assert out["components"]["news"]["score"] is None
    assert "No recent news for AAPL from Alpaca News." in out["narrative"]
    assert FORBIDDEN_EMPTY not in out["narrative"]
