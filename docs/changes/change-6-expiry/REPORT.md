# Change 6 — Expiry notice and paper auto-close

## What shipped

Open option trades expiring within the next 7 calendar days (today through day 7, America/New_York) raise an expiration notice. The notice is the existing order-confirmation certificate with an `expiry` variant: same dialog, focus trap, Escape to dismiss, paper banner, and certificate classes. It was not copied into a second component.

Each row shows symbol, strategy, expiry, and days left, soonest first. A Close button is rendered only when the existing paper close action applies (`can_close` and a ledger position id). SnapTrade rows are listed without Close.

If nothing is inside the window, the certificate returns no dialog.

The notice includes: "Positions still open at the cutoff on their expiry day will be closed automatically."

It appears on login, and again for an already-open session once per New York market day.

## How auto-close runs

The job lives in `backend/app/services/expiry_close.py`. It is scheduled in both the API process and the sentiment worker:

- **16:05 America/New_York every day** — cutoff pass. The cutoff itself is **16:00** (regular session close).
- **09:35 America/New_York Monday–Friday** — catch-up for anything still open after its expiry date.
- **Once at API startup** — same catch-up if the process was down at 16:05.

Pytest sets `PYTEST_CURRENTTEST`, which disables the scheduler so tests do not trade.

Only `account_mode == paper_funded` is loaded. A SnapTrade / `real_brokerage` account is never passed to `submit_order`. The alert endpoint may read SnapTrade positions; it does not place orders. Those rows come back with `can_close: false`.

A position is due when its OCC expiry is **before today**, or **today and the New York clock is at or after 16:00**. Equity symbols are ignored.

The close calls `execute_market_fill` (existing quote, cash, buying power, portfolio value, position delete, and fill broadcast):

- Quote price comes from the adapter. If the quote has no price, that symbol is skipped. No synthetic price is written.
- If the session is closed (weekend, or clock outside 09:30–16:00 ET), the order is not sent to the broker. The fill uses `DemoAdapter.submit_order`, the same paper path Alpaca already uses when an order is rejected.
- If the session is open and the broker raises or returns a rejected status, that same paper path fills the ledger.
- Long options are sold; short options are bought to close. A closing buy does not fail the buying-power check that applies to new risk.
- The fill and the position delete commit together. A second run finds nothing left to close, so cash and order count do not move again.

After a fill, the dashboard socket and the expiry notice both apply the broadcast: session balances update, and portfolio, positions, orders, and P&L queries refresh. Manual Close from the notice uses `POST /api/positions/{id}/close` and applies the returned balance the same way.

## Files

- `backend/app/services/occ_symbol.py` — OCC expiry parse
- `backend/app/services/expiry_close.py` — window, notice rows, idempotent close, scheduler
- `backend/app/routers/expiry.py` — `GET /api/expiry-watch`
- `backend/app/services/fills.py` — paper fallback when the market is closed or the broker rejects; closing buys skip the open-risk buying-power check
- `backend/app/services/snaptrade.py` — optional `expiry` on normalized positions (P&L math unchanged)
- `backend/app/main.py` — route and scheduler
- `backend/app/workers/run.py` — same schedule on the worker
- `backend/tests/test_expiry_close.py`
- `frontend/src/components/OrderConfirmationCertificate.tsx` — `variant="expiry"`
- `frontend/src/components/ExpiryWatchNotice.tsx` — login / once-per-market-day host
- `frontend/src/lib/expiryNotice.ts`
- `frontend/src/App.tsx`, `frontend/src/pages/Login.tsx`, `frontend/src/store.ts`, `frontend/src/api.ts`
- `frontend/src/lib/expiryNotice.test.ts`, `frontend/src/components/OrderConfirmationCertificate.test.tsx`

## Tests

```bash
backend/.venv/bin/python -m pytest backend/tests/test_expiry_close.py
frontend/node_modules/.bin/vitest run src/lib/expiryNotice.test.ts src/components/OrderConfirmationCertificate.test.tsx
```

| Test | Result |
| --- | --- |
| `test_expires_today_is_included` | Listed at 10:00 ET with 0 days left; still open before the cutoff; closed at 16:05 ET on the paper path. Cash, buying power, and portfolio value credit the quote × 100. Broker `submit_order` is not called. |
| `test_expires_in_eight_days_is_excluded` | Absent from the notice and still open after the cutoff. Cash unchanged. |
| `test_second_run_does_not_double_close` | Second pass closes 0. One order, same cash. |
| `test_read_only_account_is_not_submitted` | `real_brokerage` stays open. No quote, no submit, no order. `can_close` is false. |
| `test_no_positions_means_no_modal` | Empty certificate markup is blank. `shouldShowExpiryNotice` is false when the item count is 0, including right after login. |
| `test_broker_rejection_uses_quote_price` | Open session, broker raises, ledger still closes at the quoted price (3.37), not a stand-in. |
| `test_past_expiry_closes_when_the_market_is_closed` | Friday expiry still open on Saturday is paper-filled so it does not remain in the ledger. |
| `test_window_includes_today_and_excludes_eight_days` | Day 0 and day 7 are inside the window. Day 8 is not. |

The certificate UI test also checks the auto-close sentence, soonest-first order, the paper banner, and Close only on the row that already has a close action.

Browser click-through was not run in this session (no browser tools). Markup and the show/hide rules are covered by the Vitest cases above.
