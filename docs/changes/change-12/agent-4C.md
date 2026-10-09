# Change 12 — agent 4C

Branch: `change12/4C` from `change12/base` at `297104c`.
Worktree: `/Users/Mayank/Desktop/APEX-change12-4C`.

## What changed

After a successful sign-in, the desk asks `GET /api/expiry-watch` for open option positions inside the next 7 calendar days. That route already existed. It reads the same position rows the paper auto-close job uses. No second route was added, and `close_expiring_paper_positions` was not rewritten.

When the list is empty, login continues to the desk and no dialog is shown. When it is not empty, one certificate stays on the sign-in screen until it is dismissed. The dialog uses `role="dialog"`, a labelled title, Escape to close, and the existing focus trap. Each row shows the symbol, the strategy name when one is stored, the expiry (`Oct 9, 2026`), the strike, call or put, and long or short. The notice says those positions will be closed automatically at 16:00 America/New_York on the expiry day if they are still open.

The watch payload now includes `strike`, `right`, and `direction` from the OCC symbol and the position quantity. Prices are not invented there. The 16:00 New York close still fills through the existing quote path.

A position expiring today is included. A position 8 calendar days out is excluded. The same rule is checked in `within_alert_window` and again when the login rows are built.

## Tests

`backend/tests/test_expiry_close.py` covers the window: today is listed (including a short), 8 days out is not, and the paper close after 16:00 America/New_York still uses the quoted mark.

Frontend:

- `frontend/src/lib/expiryLoginNotice.test.ts` — today included, 8 days excluded, `Oct 9, 2026`, unknown strategy omitted.
- `frontend/src/components/ExpiryLoginCertificate.test.tsx` — empty list renders nothing; a row renders the labelled dialog, the contract fields, and the 16:00 notice, with the focus trap and Escape handler active.

## Results

Full backend suite, from `/Users/Mayank/Desktop/APEX-change12-4C/backend`, outside the sandbox:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

**1735 passed, 59 skipped, 0 failed.** One Starlette deprecation warning in `tests/test_ws.py`.

Frontend tests added, plus the existing login render tests:

`npx vitest run src/lib/expiryLoginNotice.test.ts src/components/ExpiryLoginCertificate.test.tsx src/pages/Login.test.tsx`

**7 passed** (4 new, 3 existing login tests).
