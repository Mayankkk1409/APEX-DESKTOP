# Data sources

Providers already wired in this repo. No additional vendor was added for Change 1. Secrets stay in `.env` (`ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, SnapTrade keys). Missing credentials produce an empty or error state. This app does not fill the gap with invented headlines, sentiment scores, prices, or financials.

## Equity quote (last, change, session OHLC, volume)

| Role | Provider | Code |
|---|---|---|
| Primary (US stocks and ETFs) | Alpaca Market Data snapshot (`StockHistoricalDataClient.get_stock_snapshot`, IEX then delayed SIP) | `backend/app/services/live_quotes.py` (`_alpaca_stock`) |
| Fallback | CNBC public quote cache, then NASDAQ public quote, then Yahoo Finance chart | same module (`_cnbc_quote`, `_nasdaq_quote`, `_yahoo_chart`) |
| Indexes (`SPX`, `NDX`, `DJI`, `RUT`, `VIX`, `COMP`) | CNBC, then Yahoo. Alpaca is not asked, because it does not quote these cash indexes. | `INDEX_FEEDS` in `live_quotes.py` |

`GET /market/quote/{symbol}` uses `get_live_quote`. If every feed fails, `price` stays null and `status` is `unavailable`.

Before a number is kept, `usable_positive_price` drops non-positive or non-finite prices, and `quote_mid` refuses a crossed market (`bid > ask`) or a non-positive bid or ask. That check sits in the Alpaca snapshot parser and in `_apply`, the single merge used by every quote feed.

`AlpacaAdapter.quote` still calls the demo adapter when `get_live_quote` has no price. That path marks `status` `unavailable` but can still carry a synthetic price. The dashboard ticker does not use it. See limitations below.

## OHLCV bars

| Role | Provider | Code |
|---|---|---|
| Primary | Alpaca `GET /v2/stocks/{symbol}/bars` (and the multi-symbol bars endpoint) | `backend/app/adapters/alpaca.py` `bars` |
| Fallback | Yahoo Finance chart | `yahoo_ohlc_bars` in `live_quotes.py` |
| Last resort | `DemoAdapter.bars` synthetic candles | `backend/app/adapters/demo.py` |

`GET /market/bars/{symbol}` returns that series. Indicator math reads these bars and does not call a separate indicator vendor.

## Technical indicators

Computed in-process from the bar closes, highs, lows, and volume. No indicator library was added.

| Indicator | Formula in this repo | Parameters |
|---|---|---|
| EMA | `k = 2 / (period + 1)`, seeded with the first close | 9, 21, 50, 100, 200 (`EMA_PERIODS`) |
| SMA | Rolling sum divided by the period | used by Bollinger |
| RSI | Wilder smoothing of gains and losses | period 14 |
| MACD | EMA(12) − EMA(26); signal is EMA(9) of that line | `MACD_FAST/SLOW/SIGNAL` |
| Bollinger | SMA(20) ± 2 population standard deviations | `BOLLINGER_PERIOD`, `BOLLINGER_STD` |
| SuperTrend | ATR length 10, factor 3 | `backend/app/analysis/supertrend.py` |
| Pivots | `(H + L + C) / 3`, then the R1–R5 / S1–S5 ladder | `pivot_points` |
| Historical vol | Standard deviation of log returns × √252 | `historical_vol` |

Entry point: `compute_all` in `backend/app/analysis/indicators.py`, exposed at `GET /market/indicators/{symbol}`.

`backend/tests/test_pivots.py` checks the pivot ladder against the classic identity `R3 = High + 2*(PP − Low)` for high 210, low 190, close 200. The other formulas were left as implemented; this change does not rewrite them.

A series shorter than two closes makes `rsi` return 50 for each point. That seed is the existing warmup in `indicators.py`. It is not the sentiment score.

## News

| Role | Provider | Code |
|---|---|---|
| Primary | Alpaca News `GET {ALPACA_DATA_BASE_URL}/v1beta1/news` with `symbols`, `limit`, and `include_content` | `fetch_alpaca_news` in `backend/app/services/sentiment_layer.py` |
| Article publisher | Whatever Alpaca puts in `source` (often Benzinga). The headline, summary, source, `created_at`, and `url` are kept as returned. | `score_articles` then `map_provider_news` |
| Fallback | None. There is no second news vendor in the repo. | |

Dashboard `GET /sentiment?symbol=` and Deep Scan `GET /market/sentiment/{symbol}` both call that live query for the symbol. They do not read `sentiment_items`.

Empty successful query: `No recent news for {SYMBOL} from Alpaca News.`

Feed failure (missing keys, HTTP status, transport error): `items` is empty, `status` is `unavailable`, and `caveat` / `error` is the reason returned by `fetch_alpaca_news`. The rest of the terminal stays up. The news panel offers Retry.

Article body for the reader modal is the publisher page fetched by `backend/app/services/article_reader.py`. If that fetch fails, the modal reports the error. It does not invent a body.

## Sentiment score

There is no vendor sentiment score in this repo.

| Input | Method | Label |
|---|---|---|
| Headlines | `lexicon_v1` in `backend/app/analysis/news_nlp.py` (signed lexicon over headline + summary, range −100 to +100). A missing score stays missing. Text with no lexicon hits scores 0, which the dashboard maps to the midpoint of a 0–100 scale only when the text was actually scored. | `score_method: lexicon_v1`, feed `Alpaca News` |
| Options flow and put/call | Volume, notional, and unusual-activity counts on the selected expiry chain | chain `source` |
| Social | Not wired. Weight is dropped, score stays null. | `status: unavailable` |

Composite weights when a component is present: news 40%, options flow 35%, social 15% (omitted until a feed exists), put/call 10%. Missing components are renormalized in `_weighted_composite`. A missing news score does not become 50 inside the APEX composite (`compute_apex_composite_score`).

## Fundamentals and catalyst dates

| Data | Primary | Fallback |
|---|---|---|
| Market cap, P/E, dividend yield, beta, average volume, expense ratio | NASDAQ public quote / company endpoints, merged in `live_quotes.py` | CNBC quote fields, then Yahoo chart metadata. Labeled on `Fundamentals.source`. |
| EPS, revenue, analyst targets, earnings surprise | NASDAQ public company and analyst APIs | none in repo. `backend/app/services/fundamentals_layer.py` |
| Earnings and macro calendar | NASDAQ earnings calendar and economic calendar | none |
| Dividends, splits, mergers | Alpaca `GET /v1/corporate-actions` | none |
| Sector vs SPY week return | Yahoo chart week return | Alpaca daily bars when Yahoo is empty |

Dates come from the provider row (`announcement_date`, `event_date_from_row`). A missing date stays missing.

## Options chain, Greeks, IV

| Role | Provider | Code |
|---|---|---|
| Primary | Alpaca option contracts plus option snapshots | `backend/app/adapters/alpaca.py` |
| Offline only | Internal Black-Scholes ladder when `ALLOW_OPTIONS_SIMULATOR=true` | `DemoAdapter.option_chain`, status `simulated` |

Missing keys or an empty vendor chain stay empty. The simulator is not a silent fallback.

## Brokerage account data

SnapTrade (read-only linked accounts) and Alpaca paper/live trading for orders and fills. These are account sources, not a market-data feed. Positions and balances are not used as quote or news substitutes.

## Gaps

- No second news vendor. Alpaca News is the only headline feed.
- No social sentiment feed. That pillar stays unavailable.
- No vendor technical-indicator feed. Indicators are local math on OHLCV.
- `DemoAdapter` can still synthesize quotes, bars, and option chains for offline use. `AlpacaAdapter.bars` falls through to those synthetic bars when both Alpaca and Yahoo return fewer than eight bars. `AlpacaAdapter.quote` can still attach a demo price after a live miss, with `status` `unavailable`. `get_live_quote` (the dashboard quote) does not do that.
- Bar OHLC is not passed through `usable_positive_price`. Only the quote merge and the Alpaca snapshot price do.
- `sentiment_items.score` still defaults to 50 in the table model. The dashboard and Deep Scan no longer read that table for headlines.
