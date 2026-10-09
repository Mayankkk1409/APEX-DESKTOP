# Change 12 — agent 4D

Branch: `change12/4D`. Worktree: `/Users/Mayank/Desktop/APEX-change12-4D`.

Risk Review no longer has a separate Acknowledge control. The thesis checkbox is the submit control when the saved auto-execution minimum is met and the server says the structure is executable. A score under that minimum still uses Place Trade. A structure the server will refuse stays locked, with the reason on screen before the box can be used.

## Behavior

- Eligible path: composite at or above the saved minimum, `auto_execute_eligible`, executable, and pre-trade validation passed. Checking the thesis box calls the same `POST /api/orders` as Place Trade, with `thesis_accepted` true. Success opens the existing order confirmation certificate. Failure shows the server message and does not open the certificate.
- Below the minimum: the checkbox is consent only. Place Trade stays the manual path, with the one-decimal manual-confirmation note.
- Blocked before click: stale or not-current quote, wide spread that is not confirmed, or a structure that is not tradeable. The checkbox is disabled. The server reason is shown above it. If the server sent no sentence, the line is "This order cannot be submitted right now."
- Wide spread after the spread confirmation is checked follows the same placement rule as any other scan. Auto-submit stays off unless the server still marks the structure eligible.
- Submission does not skip quote, spread, or thesis checks. `thesis_accepted` is sent on the order body. The server still rejects a scan order without it, and still re-checks the quote at submit.

Score sentences stay on the shared one-decimal formatter. The server eligibility function was not edited.

## Files

- `frontend/src/lib/riskReview.ts` — `thesisCheckboxState` (disabled, submits on accept, reason). `orderPlacement` decisions are unchanged.
- `frontend/src/components/RiskReviewOrderActions.tsx` — one thesis checkbox, the block reason, and Place Trade. No Acknowledge button.
- `frontend/src/pages/DeepScan.tsx` — checkbox submits only when `thesisState.submitsOnAccept` is true. Place Trade uses the same mutation. Certificate on success.
- `frontend/src/pages/DeepScan.order.test.tsx` — eligible checkbox, Place Trade under the minimum, stale quote, unconfirmed wide spread, missing reason, and no Acknowledge control.

## Tests

Frontend, from `frontend/` in this worktree: `npm test` (`vitest run`).

- 55 files passed, 306 tests passed, 0 failed.

No backend test was required. `executability.py`, `narrative_guard.py`, `strategy_engine.py`, `fills.py`, and Login were not edited.
