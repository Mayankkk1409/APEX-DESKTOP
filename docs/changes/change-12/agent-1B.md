# Change 12 — agent 1B (C7, C8, A4.6)

Branch: `change12/1B`. Worktree: `/Users/Mayank/Desktop/APEX-change12-1B`. Base: `change12/base` at `d014ef6`.

`backend/app/contracts.py` was not edited. This work does not call it.

## Stage 1 — Brainstorm

Approaches considered:

- Re-sort only in the Dashboard after `/market/search` returns. Rejected. Demo and Alpaca both call `search_instruments`, and the plan says not to edit the adapters or `market.py`.
- Add a fourth tier for exact name before prefix. Rejected. The spec order is exact symbol, then symbol prefix, then name.
- Change `formatCompositeScore` so it returns only `59.0`. Rejected for the existing function. `StrategyScan.tsx` and `OrderConfirmationCertificate.tsx` already import it and expect the ` / 100` scale. Those files belong to 1D. A second export, `formatCompositeDecimal`, is the one rounding path; `formatCompositeScore` calls it and keeps the scale.

Choice: rank inside `filter_symbol_hits` / `search_instruments`. Add the missing `MS` row. Debounce and cache in `frontend/src/lib/symbolSearch.ts`, and call that from Dashboard without editing `api.ts`. Point the APEX composite gauge at `formatCompositeDecimal`.

Surfaces: `search_instruments` (demo adapter, Alpaca adapter, `/market/search`), Dashboard ticker box, APEX composite gauge, certificate and strategy lines that already call `formatCompositeScore`.

Edge cases: empty query stays alphabetical by name then ticker. Case-insensitive query. Duplicate symbols still collapse. Disallowed asset classes still drop. Broker extras still cap at 25, after the new rank, then the union is ranked again so an extra exact symbol can lead a catalog prefix. A newer keystroke cancels the previous debounce. A failed fetch is not cached. `59` prints `59.0`. `62.9` stays `62.9`. Null, undefined, NaN, and Infinity stay an em dash.

## Stage 2 — Research

Code paths read on `change12/base`:

- `backend/app/services/symbol_catalog.py:129` sorted hits by `(name, symbol)` after `matches_query`.
- `backend/app/services/symbol_catalog.py:264` sorted the catalog-plus-extras list the same way.
- `CATALOG` had `MSFT` (Microsoft Corporation) and no `MS`. Banks present included JPM, BAC, WFC, C, GS, V. `BA` (The Boeing Company) and `BAC` (Bank of America Corporation) were both present.
- `matches_query` already treated symbol equality and `startswith` as a match, and a name word `startswith` as a match. It did not rank them.
- `frontend/src/pages/Dashboard.tsx:71-77` awaited `api.search` on every call. `Dashboard.tsx:296-298` called that from `onChange` with no debounce and no cache.
- `frontend/src/api.ts:111` is `search: (q) => req(.../market/search)`. Not edited (1A).
- `frontend/src/lib/scoreFormat.ts:2-4` already used `toFixed(1)` and appended ` / 100`.
- `frontend/src/components/ApexScoreScan.tsx:5-8` and `:94` formatted the gauge with a local `fmt(..., 1)`, not `scoreFormat.ts`.
- `frontend/src/lib/riskReview.ts:28-31` `formatGateScore` uses `Math.round(value * 10) / 10` and `String(rounded)`, so an integer prints without `.0`. Not edited (1D).
- `backend/app/services/scan_engine.py:824` and `:827` interpolate `{composite:g}`. Python's `g` drops a trailing `.0`. Not edited (1D in this phase).
- `backend/app/services/strategy_engine.py:2755`, `:2760`, `:2765` use `{composite:g}`. `:1478`, `:1600`, `:2769`, and `:2773` interpolate `{composite}` directly. Not edited (1D in this phase; 2A receives the file later).

Docs: `docs/changes/change-12/SPEC.md` C7, C8, and A4.6. `docs/changes/change-12/PLAN.md` Phase 1, section 1B. Change 9 report states the strategy line uses `formatCompositeScore` (`72.4 / 100`) and the risk-review sentence uses `formatGateScore` (drops a trailing `.0`).

Morgan Stanley: the firm’s Form 10-K exhibit states that its common stock trades on the New York Stock Exchange under the symbol `MS` (SEC, exhibit filed with the 2025 Form 10-K, https://www.sec.gov/Archives/edgar/data/895421/000089542126000086/exhibit41q42025_10k.htm). The 2024 Form 10-K cover table lists “Common Stock, $0.01 par value”, trading symbol `MS`, New York Stock Exchange (https://www.sec.gov/Archives/edgar/data/895421/000089542125000304/ms-20241231.htm). The same 10-K uses the words “Morgan Stanley” for the parent. The catalog row uses that wording, title case, consistent with the other equity names. Preferred depositary symbols in that exhibit (`MS/PA` and the other `MS/P*` series) were not added.

Assumption, labeled as such: a cold `/market/search` round trip was not timed. The 300 ms claim below is the in-memory catalog search plus the debounce constant and the cache hit path, not a measured browser-to-API latency.

## Stage 3 — Checklist

- [x] Exact symbol, then symbol prefix, then name
- [x] `MS` returns Morgan Stanley first, then `MSFT`
- [x] `JPM`, `V`, `C`, `T`, `KO`, `GE`, `META`, `PG`, `BA`, `DIS` return that exact ticker first
- [x] Empty query remains alphabetical by name, then ticker
- [x] Debounce under 300 ms and an in-memory cache on the Dashboard search
- [x] One rounding path in `scoreFormat.ts`; `59` → `59.0`; `62.9` stays `62.9`
- [x] APEX composite gauge uses that path
- [x] Existing `formatCompositeScore` scale (`59.0 / 100`) kept for screens this agent does not own
- [x] `contracts.py` untouched
- [x] No threshold, weight, or purchase change

## Stage 4 — Execution

- `backend/app/services/symbol_catalog.py` — `_match_tier` (`:88`) and `_hit_sort_key` (`:121`). `filter_symbol_hits` sorts by tier, then name, then ticker (`:151`). `search_instruments` re-ranks the merged extras the same way (`:287`). Catalog row `MS` / `Morgan Stanley` at `:182`.
- `backend/tests/test_symbol_catalog.py` — exact-ticker cases, the MS tier order, an extra exact symbol ahead of a prefix and a name, and a wall-clock bound for the eleven queries.
- `frontend/src/lib/symbolSearch.ts` — `SEARCH_DEBOUNCE_MS = 200` (`:4`). Cache key is the trimmed query in upper case. Cached hits resolve on this turn. A newer keystroke settles the previous promise with `null`. A rejected fetch is not stored.
- `frontend/src/lib/symbolSearch.test.ts` — debounce collapse, cache, failed fetch.
- `frontend/src/pages/Dashboard.tsx` — `runSearch` (`:77`) goes through `createDebouncedSymbolSearch`. `closeSuggestions` cancels it (`:60`). `onChange` still calls `runSearch` (`:304`). `api.ts` was not edited.
- `frontend/src/lib/scoreFormat.ts` — `formatCompositeDecimal` (`:5`) is the one-decimal formatter. `formatCompositeScore` (`:11`) appends ` / 100`.
- `frontend/src/lib/scoreFormat.test.ts` — `59.0`, `62.9`, and the scaled strings.
- `frontend/src/components/ApexScoreScan.tsx` — gauge text and `aria-label` use `formatCompositeDecimal` (`:67`, `:85`, `:96`). Pillar section scores still use the local integer `fmt`.

## Stage 5 — Testing

Backend, from `backend/`, `.venv/bin/python -m pytest -q --tb=line`:

**1496 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`), 19.68s. Exit code 0.

Baseline on `change12/base` recorded in `PLAN.md`: 1482 passed, 59 skipped, 0 failed. The difference is the 14 new catalog tests (11 parametrized ticker cases, plus the MS tier test, the extras rank test, and the timing test). `tests/test_symbol_catalog.py` alone: 24 passed.

Frontend, `vitest run` of the files this agent touched plus `scanSlides.test.tsx` (it renders `ApexScoreScan`):

**5 files, 22 tests passed.** That includes `scoreFormat.test.ts` (4), `symbolSearch.test.ts` (4), `scanSlides.test.tsx` (9), `Dashboard.brokerage.test.tsx` (3), `Dashboard.paper-brokerage.test.tsx` (2).

Use cases:

1. `MS` / `ms`: first hit symbol `MS`, name `Morgan Stanley`; second hit `MSFT`. Passed.
2. Exact tickers `JPM`, `V`, `C`, `T`, `KO`, `GE`, `META`, `PG`, `BA`, `DIS`: each query’s first hit is that symbol and the catalog name already stored for it. Passed.
3. Synthetic `MS` list: exact `MS`, prefix `MSFT`, name match `AAA` (“Aardvark MS Holdings”) in that order, even though the name match sorts first alphabetically. Passed.
4. Broker extra `ZZ`: exact, then prefix `ZZTOP`, then name `QQQZ`. Passed.
5. Eleven catalog queries together finished in under 300 ms (assertion, not a printed duration). Passed.
6. Formatter: `formatCompositeDecimal(59)` is `59.0`; `formatCompositeDecimal(62.9)` is `62.9`; `formatCompositeScore(59)` is `59.0 / 100`; `formatCompositeScore(62.9)` is `62.9 / 100`. Passed.
7. Debounce: `m` then `ms` fetches once, for `ms`. Cached `MS` does not fetch again and resolves without the debounce wait. A rejected fetch is retried. Passed.

No browser tools were available in this worktree session. Dashboard search was not clicked in a running app. The static Dashboard tests still render. The debounce behavior is covered by `symbolSearch.test.ts`, which Dashboard calls.

## Root causes

- `backend/app/services/symbol_catalog.py:129` (base) sorted matching hits by company name, then ticker. A prefix or a name that sorts earlier outranked the exact ticker. `BA` loses to `BAC` on that key because `Bank of America Corporation` casefolds before `The Boeing Company`, and `BAC` starts with `BA`. The same key was applied again to extras at `:264`.
- `CATALOG` had no `MS` row (base, between `GS` at `:159` and `V` at `:160`). `MSFT` is a symbol prefix of `MS`, so the query could not return Morgan Stanley.
- `frontend/src/pages/Dashboard.tsx:71-77` and `:296-298` (base) searched on every keystroke with no debounce and no cache.
- `frontend/src/components/ApexScoreScan.tsx:5-8` and `:94` (base) did not use the shared formatter. Its local `fmt(..., 1)` already passed one digit; the shared path is what other screens are supposed to call.
- Screens this agent does not own still drop the trailing decimal. See requests.

## Sources

- Morgan Stanley common stock, symbol `MS`, NYSE: https://www.sec.gov/Archives/edgar/data/895421/000089542126000086/exhibit41q42025_10k.htm
- 2024 Form 10-K cover table, Common Stock `$0.01` par value, symbol `MS`, NYSE: https://www.sec.gov/Archives/edgar/data/895421/000089542125000304/ms-20241231.htm
- Spec C7, C8, A4.6: `docs/changes/change-12/SPEC.md`
- File ownership: `docs/changes/change-12/PLAN.md` section 1B
- Prior formatter split: `docs/changes/change-9/REPORT.md` (strategy line `72.4 / 100`, risk review drops trailing `.0`)

Ticker names other than Morgan Stanley were already in `CATALOG`. This change did not re-verify those legal names.

## Open questions

- The first uncached keystroke waits 200 ms and then `api.search`. That HTTP call was not timed. Cached queries and the in-memory catalog search are what the tests bound to 300 ms.
- Preferred series in the 10-K exhibit (`MS/PA` and the other `MS/P*` symbols) are not in the catalog. If a broker dump includes them, they rank as prefixes after exact `MS`. Their Alpaca symbol spelling was not checked.
- `formatCompositeScore` still returns `59.0 / 100` so 1D’s current callers do not change. The bare one-decimal string is `formatCompositeDecimal`.

## Requests for other owners

- **1D** — `frontend/src/lib/riskReview.ts:28-31` `formatGateScore` prints `59` as `59`. `manualConfirmationNote` and `autoExecEligibilityLine` should call `formatCompositeDecimal` from `frontend/src/lib/scoreFormat.ts`. Deep Scan reaches that string through `autoExecEligibilityLine`. Do not edit `scoreFormat.ts`.
- **1D** — `backend/app/services/scan_engine.py:824` and `:827` use `{composite:g}`, which drops a trailing `.0`. `backend/app/services/strategy_engine.py:2755`, `:2760`, and `:2765` do the same. `:1478`, `:1600`, `:2769`, and `:2773` interpolate the raw number. Phase 1 owner is 1D. If those sentences are still unchanged when 2A takes `strategy_engine.py`, 2A should format them to one decimal without changing weights. A Python equivalent of the shared rule is `f"{composite:.1f}"` (`59` → `59.0`, `62.9` → `62.9`).
- **1D** — `StrategyScan.tsx` and `OrderConfirmationCertificate.tsx` already call `formatCompositeScore`. No edit required for the scale string. The gauge number, without ` / 100`, is `formatCompositeDecimal`.
