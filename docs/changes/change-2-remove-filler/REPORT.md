# Change 2 — Remove brokerage filler copy

## Brainstorm

The brokerage panel carried two explanatory lines that restated behavior the controls already show:

1. Under the view selector, paper mode printed a hint that the paper account is always available and then interpolated a simulated balance. The dollar amount came from the session (`portfolio_value`, then `cash_balance`, then a `100_000` fallback), so every amount was the same sentence.
2. When SnapTrade was neither down nor unconfigured, a second line explained the read-only connection and that paper mode does not require one.

Those lines do not gate connection, view mode, or paper trading. The Connect brokerage button, the paper/brokerage view selector, and the status badge already carry that behavior. Removing the sentences leaves the panel functional and avoids printing a balance in prose.

Out of scope: portfolio chart math, news providers, strategy selection, expiry jobs, and the paper-balance settings API.

## Research

Repo search before the edit (components, tests, backend, docs):

| Location | What it was |
|---|---|
| `frontend/src/components/BrokerageConnectionPanel.tsx` | Both sentences. The balance line used `paperBalance.toLocaleString(...)`, so every dollar amount was the same string. |
| `frontend/src/components/BrokerageConnectionPanel.test.tsx` | Does not assert either sentence. It checks the Connect control, paper view option, account dropdown, and SnapTrade status badges. |
| `docs/RECOMMENDATION_ENGINE.md` | API table row “Reset simulated balance + audit” for `PATCH /api/settings/paper-balance`. Different wording; not user-facing filler. Left unchanged. |

No tooltip, constant, or second component contained either sentence. Status copy that stays:

- Badge: Connected / Not connected / SnapTrade down / SnapTrade not configured.
- Missing-credentials and upstream-down notes (operational, not the removed sentences).
- View option `Paper Trading` still appends the session balance so the selector identifies the paper account. That label is not the removed sentence and is not a hardcoded dollar figure.

`paperBalance` remains only for that view option. Connect still calls `openSnapTradeConnectionPortal()`.

## Checklist

- [x] Remove the paper-account hint that appended any simulated dollar balance.
- [x] Remove the disconnected-state line about connecting for live read-only data while paper trading stays available.
- [x] Keep Connect brokerage, paper view, and the compact status badge.
- [x] Do not hardcode a balance into the removed copy.
- [x] Do not change portfolio chart math, news providers, strategy selection, or expiry jobs.
- [x] Brokerage panel tests still pass without assertion edits (they never required the removed copy).

## Files

- `frontend/src/components/BrokerageConnectionPanel.tsx` — deleted the paper-hint paragraph (`portfolio-view-paper-hint`) and the disconnected-state SnapTrade blurb.
- `docs/changes/change-2-remove-filler/REPORT.md` — this note.

## Tests

Sentence search. Patterns are concatenated in the shell so this note does not contain the removed lines. Expect no matches:

```bash
rg -n "$(printf '%s%s|%s%s|%s%s' \
  'Paper account is always ' 'available' \
  'Connect via SnapTrade for live read-only account ' 'data' \
  'Paper trading remains available without a ' 'connection')" .
```

Result: no matches.

Brokerage panel (local Vitest 2.1.9):

```bash
cd frontend && ./node_modules/.bin/vitest run src/components/BrokerageConnectionPanel.test.tsx
```

Result: 7 passed. No test file was edited. The panel tests do not look for the removed lines; they still require `brokerage-connect` and `Paper Trading`.
