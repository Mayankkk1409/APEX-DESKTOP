# Change 12 — Phase 1 integration

Branch: `change12/base`. Phase 2 was not started. `backend/app/contracts.py` was not edited. `canAutoExecute` there still raises `NotImplementedError`.

Command after every merge, from `backend/`:

`backend/.venv/bin/python -m pytest -q --tb=line`

## Merge order

No conflicts. Each branch was merged with `--no-ff` from `change12/base` at `d014ef6`.

| Order | Branch | Merge commit | Backend suite |
| --- | --- | --- | --- |
| 1 | `change12/1B` (`8302d80`) | `aed82b19efddcf819958f4358d1b4aba2d5db0d4` | 1496 passed, 59 skipped, 0 failed |
| 2 | `change12/1C` (`9789e39`) | `2c4e2561f65d373530b5d8baf86084510f066836` | 1506 passed, 59 skipped, 0 failed |
| 3 | `change12/1D` (`1fa2a42`) | `37d6a723f06dea1c2599537263c34bd921f277ae` | 1519 passed, 59 skipped, 0 failed |
| 4 | `change12/1A` (`8e21682`) | `9213096901fe597520cc20ade128e39e0ec9fdf0` | 1529 passed, 59 skipped, 0 failed |

The file lists did not overlap, so git did not stop on a conflict. Nothing was rewritten to pick one behavior over another.

## Conflicts fixed

None during the merges. The integration commit after the four green merges wires the gaps the phase notes left for this step.

## Requests applied

1. Risk Review sentences in `frontend/src/lib/riskReview.ts` call `formatCompositeDecimal` from `frontend/src/lib/scoreFormat.ts`. `formatGateScore` is gone. `59` displays as `59.0`. `62.9` stays `62.9`. No second formatter was added.
2. Scan and strategy sentences that used `{composite:g}`, a raw integer composite, `_score_token`, or `_one_decimal` now print one decimal (`59.0`, `62.9`). Score weights were not changed. The 300-second quote cap and the 10% spread cap were not changed.
3. `Guard` in `frontend/src/App.tsx` calls `restoreSession()` before it sends a missing memory token to `/login`. A successful restore does not clear symbol, expiry, or the other scan fields.
4. `useMarketSocket` follows `subscribeAccessToken`. The access token stays in memory. A socket closed with `4401` opens again when `getAccessToken()` is a different token than the one that was rejected.
5. `frontend/src/lib/brokerageApi.ts` retries a brokerage fetch once after `refreshAccessTokenOnce()` on HTTP 401. The token is not written to `localStorage`.
6. When `earnings_applicable` is false, the strategy decision and the strategy layer do not add "Earnings date is unconfirmed." An estimated date is not labeled unconfirmed, and an earnings-before-expiry sentence uses the `est.` display from 1C. A `last_close` quote is not a stale failure. During the regular session, age past `QUOTE_FRESHNESS_SECONDS` (300) is still stale.
7. Order eligibility stays `app.services.executability.can_auto_execute`. The strategy layer calls that function. The frozen stub in `contracts.py` was not given this decision.

## HIGH finding

1D reported that no order path bypasses submission validation. That is still true after the merge.

`skip_quote_check` on `execute_market_fill` defaults to false and has no caller. Acknowledge, Place Trade, the direct single-leg API, close, expiry close, and demo fill go through `enforce_submission_quotes` before a broker or demo submit. A wide spread can proceed only when `spread_confirmed` is true. Other blocks are logged and raised.

## Tests after the integration edits

Backend, same command: **1530 passed, 59 skipped, 0 failed**. The extra pass is the clock-pinned stale-quote case plus the earnings and last-close cases. The stale refetch test now uses Monday 5 October 2026 at 16:00 UTC, inside the regular session, so an after-hours run does not treat a 17-minute-old quote as last close.

Frontend, `vitest run` of the files these edits touch:

**8 files, 43 tests passed** (`riskReview`, `scoreFormat`, `marketSocket`, `brokerageApi`, `App.guard`, `api.session`, `store.session`, `scanSlides`).

The suite is green.

## Carried forward

Not built in this integration. Phase 2 has not started.

- Ledger `record` / `get`, narrative guard, and the debug view (2B). `ledger_flags` from 1C are not recorded yet.
- Knowledge-base required fields and golden scenarios (2C).
- Regime, vega sign, event-vega, DTE windows, sentiment conflicts, and rich-IV alternatives (2A). `gate_config.quote_is_stale` is still the age-only helper. The Phase 1 failure paths use `classify_quote_freshness` instead of editing that helper.
- `_pick_strike` still sorts by delta. Liquid-strike preference remains in `pick_recommended_contract`.
- An `event_risk` penalty beyond the existing earnings-before-expiry note.
- Moving the access token from JavaScript memory into an httpOnly cookie. It is not in `localStorage` or `sessionStorage`.
- Renaming the refresh cookie to the `__Host-` prefix.
- Copying the chart image into the scan session store.
- Timing a cold `/market/search` round trip in the browser. Preferred `MS/P*` symbols were not added.
- Holiday sessions when Alpaca's calendar call fails. The fallback is still weekday 09:30–16:00 America/New_York.
- C6 weight calibration. Weights were not changed.
- A missing quote timestamp is still not treated as stale, matching `quote_is_stale`. Tightening that would stop demo fills that have a price and no `as_of`.
