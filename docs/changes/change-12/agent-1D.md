# Change 12 — agent 1D

Branch: `change12/1D`. Worktree: `/Users/Mayank/Desktop/APEX-change12-1D`. Base: `change12/base` (`d014ef6`).

Spec A1, A3, A4.1–A4.5. Frozen `backend/app/contracts.py` was not edited. `canAutoExecute` there still raises `NotImplementedError`. The real decision is `can_auto_execute` in `backend/app/services/executability.py` with the same inputs and `{eligible, reasons}` shape.

## A1 audit (before the fix)

Every order path used the scan’s stored flags, or no flags, and did not re-check quote freshness or spread at submission. That is high severity.

| Path | What it did | Base location |
|---|---|---|
| Acknowledge / Place Trade (`POST /api/orders` with legs) | Refused only when the stored layer said `tradeable` was false (`Strategy layer is not tradeable — validation blocked this structure`) or `checks_passed` was false. No live quote refetch. `execute_strategy_legs` was not given `checks_passed`, so its own refuse was a no-op. | `backend/app/routers/portfolio.py:317-327`, call at `:359` |
| Direct API (legs omitted) | Buying power and `quote.price` only. | `backend/app/routers/portfolio.py` single-leg branch |
| Close position | `execute_market_fill` with no freshness or spread check. | `backend/app/routers/portfolio.py` `close_position` |
| Expiry close | Same `execute_market_fill`. The skip log stored the exception type name, not the reason. | `backend/app/services/expiry_close.py:169` |
| Demo fill | `_submit_for_fill` falls through to `DemoAdapter` after a broker rejection or missing keys, with no quote re-check of its own. | `backend/app/services/fills.py` `_paper_submit` / `_submit_for_fill` |

After this change, Acknowledge, Place Trade, the direct single-leg API, close, expiry close, and demo fill all go through `enforce_submission_quotes` before any broker or demo submit. `skip_quote_check` exists and defaults to false. Nothing calls it. A wide spread is the only case that may proceed, and only when `spread_confirmed` is true. Every block is logged with `order blocked` and the reason.

## Root causes

1. Risk Review armed Acknowledge from the score alone. `autoSubmitArms` returned true when the composite was at or above the minimum and the structure was defined-risk, even when `serverAutoSubmit` was false (`frontend/src/lib/riskReview.ts:19-23` on base). The strategy slide hid the auto-exec line when checks failed, so the kicker stayed `NOT EXECUTABLE`, while Risk Review still said auto-execute eligible.
2. Acknowledge then hit the stored-scan guard and returned `Strategy layer is not tradeable — validation blocked this structure` (`backend/app/routers/portfolio.py:317-318` on base). The quote was not refetched, so a quote that went stale after the scan was not rejected for staleness.
3. Deep Scan hardcoded `formatOrderType("market", orderAssetClass)`, which rendered `market · us_option` (`frontend/src/pages/DeepScan.tsx:190` on base). Option fills could be sent as market orders.
4. Candidates were ordered by score only. A blocked name with a slightly higher score stayed the Best Match. Ranking lives in `strategy_recommendation.py`, which this agent does not own. The preference is applied after that rank, only when per-name executability flags are present.
5. Risk Review copy included the filler sentences and the raw asset class (`backend/app/services/scan_engine.py:765-766` on base).
6. A long put against shares already held kept the registry name Married Put on the card. The registry name is still Married Put so validation stays valid. The display label is Protective Put.

## Changes

- `backend/app/services/executability.py` (new). One decision: eligible only when auto-execution is not explicitly off, `executable` is true, validation passed, and composite is at least the saved minimum (default 85 when settings omit it). Missing flags are not a pass. `eligibility_sentence` is the line both screens show.
- Stale, missing, or suspect quotes are fetched once more. If the second read is still bad, submission raises `Quote not current` and includes the timestamp when there is one. A price with no timestamp is not treated as stale. `quote_is_stale` already returns false without a timestamp, and demo quotes have a price and no `as_of`. Tightening that would block every demo fill.
- A spread wider than the cap (default 10% of mid, strict `>`, not loosened) blocks auto-execute. Equal to 10% of mid is not wider, matching `options_rules._le`. Manual submit of a wider spread requires `spread_confirmed`. The confirmation text states the spread, the cap, and estimated slippage in dollars (half the bid/ask width × quantity × multiplier).
- Option orders are limits: buy at the ask, sell at the bid. If that side is missing, an existing limit or a positive price is kept. A market order is not sent for `us_option`.
- `strategy_decision` reorders only when `executable_by_name` is passed. If none are executable, the best-ranked real strategy stays. The card is not titled NO TRADE or Wait for IV Crush.
- Scan promotion (`scan_engine._promote_close_executable`) swaps in an executable defined-risk candidate only when it is within `CLOSE_SCORE_GAP` of the blocked winner and its own layer is executable.
- Held shares: `Uses N of your N shares. Using N shares already held … No additional shares are bought.`
- `structure_label` is Protective Put when the legs are one stock leg plus one long put and the shares are already held. `selected_strategy` stays Married Put.
- Risk Review narrative no longer mentions Alpaca paper, WebSocket, OCC symbol boilerplate, or `us_option`. It keeps legs, quantities, order type, limit, estimated cost or credit, and account impact. Broker fees are not on the quote, so no dollar fee is invented.

## Tests

- `backend/tests/test_executability.py`: score above, equal to, and below the minimum; JPM 62.9 vs minimum 50 with `quote 17 min old` does not say Auto-execute eligible; every QA row in `docs/qa/APEX_QA_Test_Results.csv` whose strategy status is NOT EXECUTABLE and whose Risk Review said Auto-execute eligible (27 or more) is replayed the same way; a stale quote is refetched once and then rejected with no submit; wide spread states slippage and blocks until confirmed; a spread equal to 10% of mid is not rejected; demo fill is not called when checks failed; limits are ask/bid; a close-score executable candidate outranks a blocked one; a far gap and an all-blocked set keep the real name; held shares are a Protective Put and the note counts them.
- Updated owned assertions in `test_strategy_engine.py`, `test_card_filter_gates.py`, `test_stock_leg.py`, `riskReview.test.ts`, `orderFormat.test.ts`, `DeepScan.order.test.tsx`, `OrderConfirmationCertificate.test.tsx`.

## Results

- Backend: `1495 passed, 59 skipped, 0 failed` (`pytest -q --tb=line` from `backend/`, worktree on `PYTHONPATH`). Baseline on `change12/base` was 1482 passed, 59 skipped.
- No order path bypasses submission validation. Acknowledge, Place Trade, the direct single-leg API, close, expiry close (`submission_path="expiry_close"`), and demo fill all call `enforce_submission_quotes` before a broker or demo submit. `skip_quote_check` defaults to false and has no caller.
- Frontend files touched: 6 files, 47 tests passed (`riskReview`, `orderFormat`, `certificateLegs`, `DeepScan.order`, `OrderConfirmationCertificate`, `scanSlides`).
- The app was not opened in a browser. The Risk Review and strategy-slide behavior above was checked through those tests.

## Sources

- `docs/changes/change-12/SPEC.md` A1, A3, A4.1–A4.5.
- `docs/changes/change-12/PLAN.md` ownership and frozen contracts.
- `docs/qa/APEX_QA_Test_Results.csv` for the NOT EXECUTABLE / Auto-execute eligible rows.
- `backend/app/analysis/gate_config.py` `QUOTE_FRESHNESS_SECONDS`, `quote_is_stale`, `refuse_if_checks_failed`. Called, not edited.

## Open questions

- The spec says a non-executable candidate must not outrank an executable one with a close score. It does not define close. `CLOSE_SCORE_GAP = 5.0` is inside the ordinary matrix bonuses of 1–6. It is a choice, not a figure from the spec.
- There is no broker fee on the order payload. The review says fees are not on this quote. A dollar fee was not invented.
- A missing quote timestamp is not treated as stale, matching `quote_is_stale`. If product wants “no timestamp means not current,” demo and price-only quotes need a timestamp first or every paper fill stops.

## Requests for other owners

- 1B: during integration, apply `formatCompositeScore` from `frontend/src/lib/scoreFormat.ts` to the composite shown on Risk Review. This branch formats the eligibility sentence to one decimal inside `eligibility_sentence` and `formatGateScore`. Do not add a second shared formatter. `scoreFormat.ts` was not edited.
- 1C: submission reads `as_of`, `bid`, and `ask` on the live quote. Those fields are what make freshness and the limit real. This agent does not edit 1C files. Demo quotes that have a price and no timestamp remain fillable.
- Integration: call `app.services.executability.can_auto_execute`. Do not implement the decision by editing `contracts.py`.
