# Change 12 — agent 1C

Branch: `change12/1C`. Worktree: `/Users/Mayank/Desktop/APEX-change12-1C`. Base: `change12/base` (`d014ef6`).

`backend/app/contracts.py` was not edited. `QuoteMeta` and `EarningsInfo` are imported and filled in the modules this agent owns.

## Stage 1 — Brainstorm

Approaches considered:

- Loosen the 5-minute quote age or the 10% spread cap so indicative quotes stop failing. Rejected. The spec forbids loosening those thresholds, and a wider cap would admit the wide-spread names from the QA run.
- Buy Algo Trader Plus so the process could switch the feed to OPRA. Rejected. No purchase. The cost is recorded for a team decision.
- Treat a missing earnings date as the string `none`, or invent 28 October 2026 for Alphabet because MarketBeat lists it. Rejected. Unknown stays a data gap. A provider date is stored only as estimated.
- Change `scan_engine.py` or `strategy_recommendation.py` so SPY and QQQ stop emitting "Earnings date is unconfirmed." Those files are not owned here. The earnings payload now says the check does not apply. The owner has to read that field.

Choice: attach the frozen `QuoteMeta` on stock and option quotes, classify freshness with the market calendar without changing `QUOTE_FRESHNESS_SECONDS`, prefer strikes that already clear the §5.6 open-interest and volume gates, and resolve earnings as confirmed (IR), estimated (provider), or unknown.

## Stage 2 — Research

Code paths:

- Options feed selection is `AlpacaAdapter.feed` in `backend/app/adapters/alpaca.py` (paper → `indicative`, live → `opra`). Snapshots are requested with that `feed` query parameter. No `QuoteMeta` was attached.
- Stock snapshots in `backend/app/services/live_quotes.py` try IEX, then `DELAYED_SIP`, and did not record which feed answered.
- Age-only staleness lives in `backend/app/analysis/gate_config.py` `quote_is_stale` (5 minutes). `backend/app/services/strategy_engine.py` `suspect_quote_failures` calls it. Neither file is owned here.
- Recommended-contract ranking in `backend/app/services/options_analysis.py` `pick_recommended_contract` sorted by score only. `strategy_engine._pick_strike` (not owned) still sorts by delta only.
- Earnings dates in `backend/app/services/fundamentals_layer.py` `_earnings_calendar` returned `next_date` or null with no confirmed / estimated / unknown status. `backend/app/services/scan_engine.py` sets `earnings_date_confirmed = bool(earnings_next)` and, when a calendar dict exists, passes `False`. `strategy_recommendation.py` appends "Earnings date is unconfirmed." when that flag is `False`.
- IV rank in `backend/app/services/volatility_intel.py` copied `compute_iv_rank`, which falls back to an HV ratio and labels it `iv_rank`.

Docs consulted are listed under Sources. No API keys were printed. No data plan was purchased.

## Stage 3 — Checklist

- [x] QuoteMeta on stock quotes and on each option contract (provider, feed, quotedAt, receivedAt, bid, ask, sizes, isStale, staleReason)
- [x] Indicative vs OPRA labeled from the feed this process actually requests
- [x] Outside regular hours: `staleReason` `last_close`, `isStale` false
- [x] Delayed indicative feed labeled `delayed`; during the session an age past 300 seconds is still stale
- [x] Spread, OI (500), and volume/OI (25%) numbers unchanged
- [x] Liquid strikes preferred in `pick_recommended_contract` before an illiquid strike is the candidate
- [x] Missing earnings is `unknown` with `date: null`, never the string `none`
- [x] Confirmed only with an IR source; provider dates are estimated and the display ends with `est.`
- [x] Conflict or a missing stock date is unverified and does not invent a date
- [x] JPM, GS, C, JNJ, UNH dates left at 2026-10-13 where IR confirms that date
- [x] GOOGL 2026-10-28 stored as estimated
- [x] SPY and QQQ classified as ETFs; `earnings_unconfirmed_applies` is false
- [x] Inverted put skew, crossed markets, and IV outside the chain range written to `ledger_flags`
- [x] HV-proxy IV rank is a data gap on the volatility payload
- [x] Full backend suite green

## Stage 4 — Execution

Root causes (pre-change):

| Defect | Where |
| --- | --- |
| No quote metadata | `backend/app/adapters/alpaca.py` feed assignment; `backend/app/services/live_quotes.py` `_quote_from_bundle` |
| Staleness ignores the session | `backend/app/analysis/gate_config.py` `quote_is_stale` (age > 300s only). Not edited. Classifier added in `options_rules.py` |
| Illiquid strike can be the candidate | `backend/app/services/options_analysis.py` `pick_recommended_contract` |
| Missing earnings has no status | `backend/app/services/fundamentals_layer.py` `_earnings_calendar` |
| ETF still reaches the unconfirmed sentence | `backend/app/services/scan_engine.py` around the `earnings_date_confirmed = bool(earnings_next)` assignment, and `backend/app/services/strategy_recommendation.py` when that flag is `False`. Not edited |
| No skew / bad-quote ledger flags | `backend/app/services/options_analysis.py` chain summary |
| HV proxy stored as IV rank | `backend/app/services/volatility_intel.py` `build_volatility_payload` |

Changes:

- `backend/app/analysis/options_rules.py` — market-calendar freshness, `build_quote_meta`, §5.6 liquidity helper (same 500 and 0.25), chain flags.
- `backend/app/schemas/market.py` — `QuoteMetaModel` on `Quote` and `OptionContract`.
- `backend/app/services/live_quotes.py` — meta on every quote; IEX vs delayed SIP recorded; Alpaca `/v2/calendar` when keys exist, otherwise weekday 09:30–16:00 America/New_York.
- `backend/app/adapters/alpaca.py` — option contracts stamped with the requested feed.
- `backend/app/adapters/demo.py` — demo meta uses feed `other` (it is not Alpaca indicative or OPRA). Chain `feed` stays `indicative` so existing chain labels do not change.
- `backend/app/services/options_analysis.py` — liquid strike first; `ledger_flags`.
- `backend/app/services/fundamentals_layer.py` — `EarningsInfo` resolution.
- `backend/app/services/catalyst_calendar.py` — `date_status` and `est.` display; ETF note.
- `backend/app/services/volatility_intel.py` — feed, timestamp, IV-rank gap when the rank is only an HV proxy.
- `backend/app/routers/market.py` — `/market/feed` adds `quote_feed` and `feed_delayed`.
- `frontend/src/lib/quoteMeta.ts`, `FundamentalsScan.tsx`, `CatalystCalendar.tsx` — feed line and `est.`

## Stage 5 — Testing

Command, from `backend/` in this worktree, using the main checkout's virtualenv so imports resolve to this worktree:

`python -m pytest -q --tb=line`

Result: **1492 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). Baseline on `change12/base` was 1482 passed, 59 skipped. The 10 new tests are the difference.

| Test | What it checks |
| --- | --- |
| `test_indicative_feed_is_labeled_delayed_and_opra_is_not` | Indicative vs OPRA, sizes, frozen `QuoteMeta` |
| `test_outside_regular_hours_quote_is_last_close_and_threshold_stays` | Saturday quote is last close; 301s during the session is still stale; 299s is not; delayed does not loosen the cap |
| `test_googl_earnings_date_is_estimated_not_confirmed` | 2026-10-28, status `estimated`, display `2026-10-28 est.` |
| `test_spy_and_qqq_skip_the_unconfirmed_earnings_check` | ETF skip |
| `test_confirmed_ir_date_is_kept_and_a_conflict_is_unknown` | JPM GS C JNJ UNH stay 2026-10-13; a clash or a missing date is unknown, not `none` |
| `test_inverted_put_skew_and_bad_quotes_are_flagged` | inverted put skew, bid > ask, IV outside the chain range |
| `test_liquid_strike_is_preferred_before_an_illiquid_one` | OI and volume gates before the illiquid strike |
| `test_alpaca_paper_requests_indicative_and_live_requests_opra` | Feed actually requested |
| `test_missing_iv_history_is_a_gap_not_an_hv_proxy` | IV rank gap |
| `test_quote_bundle_carries_quote_meta` | Stock quote meta |

## Sources

Alpaca, fetched 5 October 2026:

- [About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api). Trading API Basic is the default for paper and live accounts and is free. Equities: IEX. Options: Indicative Pricing Feed. Historical options on Basic exclude the latest 15 minutes, 200 calls/min, 200 option websocket quotes. Algo Trader Plus is $99/month: all US stock exchanges, OPRA, no 15-minute historical restriction, 10,000 calls/min, 1,000 option websocket quotes. Broker API (not this app's Trading API path): Standard and StandardPlus3000 add indicative options at $1,000/month; StandardPlus5000 is $1,000/month with options included; StandardPlus10000 is $2,000/month with options included.
- [Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data). Indicative quotes are derivatives, not OPRA quotes. Indicative trades are delayed 15 minutes. OPRA is the consolidated BBO and is subscription-only.
- [Real-time Option Data](https://docs.alpaca.markets/us/docs/real-time-option-data). The websocket path is `wss://stream.data.alpaca.markets/v1beta1/{feed}` with `indicative` or `opra`.
- [Alpaca data pricing page](https://alpaca.markets/data). Algo Trader Plus listed at $99/mo.

This app's paper adapter sends `feed=indicative`. Live mode sends `feed=opra`. A live account still on Basic is not entitled to OPRA; the adapter already returns `no_entitlement` on HTTP 401/403. The label is the feed requested, not proof a plan was bought.

Earnings, fetched 5 October 2026. Dates that match were not changed.

- JPM: [JPMorganChase IR](https://www.jpmorganchase.com/ir/news/2026/jpmc-to-host-third-quarter-2026-earnings-call). Tuesday, October 13, 2026. Results approximately 7:00 a.m. ET. Call 8:30 a.m. ET. The spec's "about 6:45 a.m." is not the sentence on that IR page. The calendar date is 13 October either way.
- GS: [Goldman Sachs press release](https://www.goldmansachs.com/pressroom/press-releases/2025/conference-call-dates-to-announce-4q25-and-2026-earnings-results). Third quarter 2026 – Tuesday, October 13, 2026.
- C: [Citigroup press release](https://www.citigroup.com/global/news/press-release/2026/citi-third-quarter-2026-earnings-call). Tuesday, October 13, 2026. Results approximately 8 a.m. ET. Call 11 a.m. ET.
- JNJ: [Johnson & Johnson IR](https://investor.jnj.com/events-and-presentations/events/event-details/2026/Johnson--Johnson-Third-Quarter-2026-Earnings-Call/default.aspx). Oct 13, 2026 8:30 AM ET.
- UNH: [UnitedHealth Group newsroom](https://www.unitedhealthgroup.com/newsroom/2026/2026-09-15-uhg-announces-q3-earnings-release-date.html). Tuesday, October 13, 2026, before the market opens. Call 8:00 a.m. ET.
- Alphabet: [abc.xyz/investor](https://abc.xyz/investor/) and the Q2 2026 call page do not list a Q3 2026 date. [MarketBeat](https://www.marketbeat.com/earnings/reports/2026-10-28-alphabet-inc-stock/) lists 10/28/2026 after the close. [Public.com](https://public.com/stocks/goog/earnings) lists an expected 2026-10-28. Stored as estimated, not confirmed. If a live NASDAQ date disagrees with 2026-10-28, the resolver marks the date unverified and stores no date.

The 10–45 day window after a calendar quarter-end is a convention used only to flag that an unverified stock date could fall inside an expiry. It is not a company earnings date.

## Open questions

- When Alpaca's calendar call fails, freshness uses weekday 09:30–16:00 America/New_York and does not know holidays. A holiday session could be graded as regular hours.
- JPM's IR page says results at approximately 7:00 a.m. ET. A secondary calendar (MarketScreener) listed 6:45 a.m. The date was not changed.
- `strategy_engine.suspect_quote_failures` still calls `quote_is_stale`, so a closed-session quote can still be "Stale or suspect quote" until that owner switches to `QuoteMeta`.
- SPY and QQQ will still receive "Earnings date is unconfirmed." until `scan_engine` passes a null confirmation flag when `earnings_applicable` is false.

## Requests for other owners

**1D** (`scan_engine.py`, `strategy_engine.py`, `StrategyScan.tsx`, `types.ts`):

- When `earnings_calendar.earnings_applicable` is false (SPY, QQQ, other ETFs and indexes), pass `earnings_date_confirmed=None`, not `False`, so the unconfirmed sentence is not added.
- When `date_status` is `estimated`, show `earnings_calendar.display` (it already ends with ` est.`). Do not append "Earnings date is unconfirmed." for that case.
- When `date_status` is `unknown`, keep the date null. Do not render the string `none`.
- In `suspect_quote_failures` and `_pick_strike`, use `classify_quote_freshness` / `quote_meta.isStale`. `staleReason == "last_close"` is not a failure. During the session, age over `QUOTE_FRESHNESS_SECONDS` (300) is still stale. Prefer `contract_clears_oi_and_volume` before declaring the name non-executable. `pick_recommended_contract` already sets `liquidity_gate_cleared`.
- If `earnings.event_risk` is true, apply the existing earnings-before-expiry penalty. Do not change composite weights.
- Optional: add `quote_meta` and `date_status` to `types.ts`. Fundamentals and the catalyst calendar already read them locally.

**2A** (`strategy_recommendation.py`, `gate_config.py` `quote_is_stale` and `earnings_before_expiry`):

- Replace the age-only stale check with the market-hours result from 1C. Do not loosen 300 seconds.
- Do not emit "Earnings date is unconfirmed." for `securityType` `etf` or `index`, or for an estimated date that already carries `est.`

**2B** (`evidence_ledger.py`):

- Record `ledger_flags` on the chain payload. Codes: `inverted_put_skew`, `crossed_market`, `iv_outside_chain_range`. Each flag has value, threshold, source, feed, and timestamp. This agent did not edit the ledger.
