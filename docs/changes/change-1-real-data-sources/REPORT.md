CHANGE: 1 — Real data sources

Stage 1 — Brainstorm: approaches, choice, surfaces, edge cases

Approaches considered:
- Keep reading `sentiment_items` and only change the empty sentence. Rejected. The panel would still wait on a background worker and could show nothing after a successful live feed.
- Add another news vendor. Rejected. Alpaca News is already the headline client, and a new paid provider was out of scope.
- Fetch Alpaca News live for the active symbol on the dashboard and on Deep Scan, and label lexicon sentiment that is already computed in `news_nlp.py`.

Choice: `GET /sentiment?symbol=` calls `fetch_alpaca_news` for that symbol. Deep Scan already called the same client per symbol. Articles keep the provider headline, publisher `source`, `created_at`, and `url`. Sentiment numbers stay `lexicon_v1` over that text. Indicators stay the existing OHLCV formulas. Quote prices go through the existing merge in `live_quotes._apply`, which now drops a non-positive price and a crossed bid/ask.

Surfaces: Dashboard news list, Deep Scan news list, `GET /sentiment`, `GET /market/sentiment/{symbol}`.

Edge cases: symbol with articles; symbol whose query returns an empty list; missing credentials or HTTP error; symbol Alpaca does not recognize; a closed session (weekend) that must not invent headlines when the payload is empty, and must not replace real weekend articles with filler.

Stage 2 — Research: code paths, docs consulted, findings, assumptions

Code paths:
- Dashboard empty copy was hardcoded in `backend/app/routers/watchlist.py` after a read of `sentiment_items`.
- Live headlines already existed in `fetch_alpaca_news` (`GET /v1beta1/news` on the Alpaca data host) and in `build_sentiment_layer`.
- Publisher fields are normalized in `score_articles` (`headline`, `source`, `created_at` → `published_at`, `url`).
- Sentiment math is `lexicon_v1` in `backend/app/analysis/news_nlp.py`. Options flow and put/call come from the selected chain. Social is explicitly unavailable.
- Quotes: Alpaca snapshot, then CNBC, NASDAQ, Yahoo (`live_quotes.py`). Indexes skip Alpaca.
- Bars: Alpaca stock bars, then Yahoo, then `DemoAdapter` synthetic candles.
- Indicators: `backend/app/analysis/indicators.py` and `supertrend.py`, from those bars. Pivot identity is already tested in `backend/tests/test_pivots.py`.
- Fundamentals and calendars: NASDAQ public APIs, Yahoo, Alpaca corporate actions (`fundamentals_layer.py`, `catalyst_calendar.py`).

Docs consulted: `backend/app/services/live_quotes.py` module note, `catalyst_calendar.py` source list, `news_nlp.py` method note, `.env.example` (names only). No new provider keys.

Findings: the forbidden sentence was the dashboard path, not Deep Scan. Deep Scan already queried Alpaca per symbol but said "No news articles for this symbol." A missing sentiment composite in `build_sentiment_layer` had been forced to 50; that path now stays null. `HEAD` sentiment still described coverage as "thin today" without a provider error.

Assumptions: Alpaca `source` (often Benzinga) is the article's publisher, and "Alpaca News" is the feed name. A lexicon hit-score of 0 is a real neutral read of text that was returned, not a placeholder for a failed fetch. Test runs clear Alpaca keys, so endpoint tests monkeypatch `fetch_alpaca_news`. A separate local probe used the configured keys and did not print them.

Stage 3 — Checklist: completed checkboxes

- [x] Audit data types and name the existing provider for each
- [x] News is a live per-symbol Alpaca query
- [x] Each article shows publisher, timestamp, and link when the payload includes them
- [x] Empty successful query says "No recent news for {SYMBOL} from Alpaca News."
- [x] Forbidden sentence is gone; that empty state does not say "desk" or "stored"
- [x] Feed failure returns the provider reason, an empty list, and a Retry control
- [x] Sentiment is `lexicon_v1` or absent; a missing composite is not written as 50
- [x] Indicators left as OHLCV formulas already in the app; pivot reference test kept
- [x] Non-positive prices and crossed bid/ask dropped in the existing quote merge
- [x] `/docs/data-sources.md` written from providers already in the repo
- [x] Tests cover the forbidden string and a mapped Alpaca article (source, timestamp, url)

Stage 4 — Execution: files changed and why

- `backend/app/routers/watchlist.py` — dashboard news route queries Alpaca for the requested symbol instead of the local table.
- `backend/app/services/sentiment_layer.py` — public `fetch_alpaca_news`; empty copy names the symbol and Alpaca News; failure text is the feed error; missing composite stays null.
- `backend/app/services/news_authenticity.py` — shared empty sentence; mapped rows keep `url` and `score_method: lexicon_v1`.
- `backend/app/services/live_quotes.py` — `usable_positive_price` and `quote_mid` on the snapshot parser and `_apply`.
- `backend/tests/test_news_authenticity.py` — forbidden copy, mapped article, five feed cases.
- `backend/tests/test_live_quotes.py` — negative price and crossed market.
- `frontend/src/api.ts` — `sentiment(symbol)` (staged without an unrelated brokerage status helper that was already in the working tree).
- `frontend/src/types.ts` — article url, nullable score, lexicon method.
- `frontend/src/pages/Dashboard.tsx` — news panel for the active symbol, link, timestamp, publisher, retry. Search-suggestion edits already in the working tree were not part of this commit.
- `frontend/src/components/SentimentScan.tsx` — same empty copy, publisher, time, link, retry.
- `frontend/src/components/SentimentScan.test.tsx` — rendered empty, error, and article cases.
- `docs/data-sources.md` — primary and fallback per data type.
- `docs/changes/change-1-real-data-sources/REPORT.md` — this report.

Stage 5 — Testing: tests, at least 5 use cases, results, manual checks

Backend: `python3 -m pytest tests/test_news_authenticity.py tests/test_live_quotes.py tests/test_sentiment_fundamentals.py -q` → 32 passed.

Frontend: `npx vitest run src/components/SentimentScan.test.tsx src/pages/Dashboard.brokerage.test.tsx src/pages/Dashboard.paper-brokerage.test.tsx` → 8 passed.

Use cases:
1. Symbol with news. Live `fetch_alpaca_news` for AAPL on 2026-10-04 returned 3 articles, all mapped. First row: source `benzinga`, `published_at` `2026-10-04T11:00:23Z`, url present, `score_method` `lexicon_v1`. Unit test `test_symbol_with_news_maps_source_timestamp_and_link` passed. UI test renders publisher, timestamp, and href.
2. Symbol with no news. Unit test `test_symbol_with_no_news_uses_neutral_empty_copy` expects `No recent news for AAPL from Alpaca News.` and status `empty`. Passed.
3. Provider failure. `test_provider_failure_returns_reason_and_no_headlines` expects caveat `News feed HTTP 503`, no items, no forbidden sentence. Passed. Existing test still expects the credentials sentence when keys are absent. UI test shows the HTTP reason and Retry.
4. Invalid symbol. Live query for `ZZZZNOTREAL` returned 0 articles and caveat `No recent news for ZZZZNOTREAL from Alpaca News.` Unit test of the same shape passed.
5. Market closed / weekend. 2026-10-04 is a Sunday. The AAPL query returned only those Benzinga rows; it did not add filler. Unit test `test_weekend_empty_feed_does_not_invent_headlines` forces an empty Sunday-style payload for SPY and expects the neutral sentence, `fear_greed` null, and none of the old seed headlines. Passed.

Manual: no browser session was available in this run, so the panels were checked with React static markup (vitest), not by clicking a running terminal. The live Alpaca call above is the provider check. Keys were not printed.

Defects found and fixed:
- Dashboard showed "No live Alpaca headlines are stored for this desk yet." when the table was empty, even if Alpaca could be queried.
- Deep Scan empty news said "No news articles for this symbol." and did not offer retry on a feed error.
- Mapped dashboard rows omitted the article url.
- `build_sentiment_layer` turned a missing composite into 50. It is now null, band `Unavailable`.
- A negative last price or a bid above the ask could enter the quote bundle. Both are dropped before `_apply` keeps them.

Out-of-scope findings:
- `AlpacaAdapter.bars` still falls through to `DemoAdapter` synthetic candles when Alpaca and Yahoo return fewer than eight bars. `AlpacaAdapter.quote` can still attach a demo price after a live miss, marked `unavailable`. Dashboard quotes use `get_live_quote`, which does not invent a price.
- Bar OHLC is not run through `usable_positive_price`.
- `sentiment_items.score` still defaults to 50 on the model. The dashboard and Deep Scan no longer read that table for headlines. The worker can still write lexicon rows there.
- `rsi` returns 50 when the close series has fewer than two points. That warmup was left in place.
- Other dirty files (portfolio P&L, auto-exec copy, strategy, an untracked change-2 report) were not edited or committed.
- Search-suggestion behavior already modified in `Dashboard.tsx`, and `api.brokerageStatus`, stayed in the working tree and out of this commit.

Open questions / limitations:
- There is no second news vendor. An Alpaca outage is an error plus Retry, not another feed.
- Social sentiment has no provider in the repo, so that weight stays dropped.
- A quiet symbol and an unknown symbol look the same when Alpaca returns HTTP 200 and an empty list: the neutral empty sentence. An HTTP error is a different state.
- Weekend sessions can still carry real articles. Emptiness is whatever Alpaca returned, not an assumption that markets being closed means "no news."
