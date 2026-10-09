# Options polish

Branch `change12/base`. Base for this work is `4ea90be` (shared SQLite OTP hash). This report does not claim the app is production ready. The full pytest suite and the full frontend suite were not run.

`backend/app/services/otp.py` and `backend/app/services/signup_email.py` were not edited. `POST /auth/otp/verify` still calls `verify_otp(..., db=db)`.

## Implemented / verified

### Options fills and cash

- `AlpacaAdapter.quote()` returns `source="unavailable"` and `price=None` when the live price is missing. It does not substitute a demo price.
- Missing broker credentials stay a rejected live result unless the options simulator is explicitly allowed. That path is labeled `venue=simulation` and `broker=demo_paper`. HTTP errors and exceptions stay rejected.
- `execute_market_fill` does not mark a live order filled when the broker omits an execution price. Cash uses `filled_avg_price` times the filled quantity. A one-contract fill at 3.90 debits 390.00 before fees.
- Duplicate broker ids do not debit twice. A later larger partial applies only the quantity delta.
- Position basis: same-direction adds are size-weighted; a partial close or short buyback keeps the remaining average; a full close removes the position.
- A generic broker rejection during the session is not rewritten into a paper fill. Closed-session paper fills stay labeled simulation and use the working quote as that simulation's price.
- `quoteSourceLabel` keeps `indicative`, `opra`, and `demo`.

Evidence: `backend/.venv/bin/python -m pytest` on the files listed below — **123 passed**, 1 warning, 41.09s (2026-10-09). The warning is the existing Starlette `httpx` deprecation in `backend/tests/test_ws.py`.

Covered cases include unfilled ack, partial fill, duplicate events, rejection, the 3.90 debit, and basis increase / partial close / full close / short cover.

### Home dashboard

- `/dashboard` renders `HomeDashboard`. `/app` stays the options desk.
- A fresh login restores `/dashboard`. Deep links to `/app`, `/scan`, `/portfolio`, and `/settings` still restore.
- The APEX mark and word link to `/dashboard`.
- Featured names are the catalog list (SPX, AAPL, MSFT, NVDA, QQQ, IWM), not a "popular" ranking. Unknown money renders as an em dash. Paper and brokerage are separate queries. Recent scans reopen with `reopenScanId` and do not POST a new scan (`staleTime: Infinity`, `refetchOnMount: false`).

Evidence: frontend `vitest run` on the files listed below — **6 files, 17 tests passed**, 969ms. `useLayoutEffect` SSR warnings are from static render and were already present on these pages.

### Search hover and chart

- Suggestion rows highlight on the full `[role="option"]` row in light and dark (`--apex-row-hover`). Transition is 140ms. The left border stays 2px transparent, so the row does not shift. Keyboard selection still uses `aria-selected`.
- Fullscreen is the `desk--chart-full` layout (`100dvh`), not the Fullscreen API.
- `poly()` uses M for the first finite point and L for contiguous finite points. A non-finite value lifts the pen.

Evidence: `ChartOverlay.test.tsx`, `Dashboard.fullscreen.test.tsx`, and the CSS rules in `frontend/src/index.css`.

### Sign-in verification window

- The rolling 24-hour skip is gone. Fresh login skips the emailed code only on a trading day when the device was verified at or after the most recent NYSE regular open (09:30 America/New_York, existing holiday list).
- Weekend and full-day holiday fresh logins require a code.
- An existing session stays valid through the close and the following non-trading time, and expires at the next regular open. Access tokens carry `vfy`. Protected HTTP and the market websocket reject an expired verification with `Sign-in verification expired` and do not send mail. Refresh does not email. The client ends the session on that detail before a silent refresh, so the mutation is not replayed.
- The emailed code remains the shared `OtpCode` row (600-second TTL is unchanged in this diff).

Evidence: `test_fresh_login_follows_the_regular_open_not_a_rolling_day` and `test_verified_device_skips_until_the_next_regular_open` inside the 123 passed tests.

### Efficiency (only where the code was doing extra work)

- The desk quote poll is off while the market socket reports connected, and 10s otherwise.
- Logout calls `queryClient.clear()` before dropping the user.
- Reopening a scan does not POST `/scan` again.

No shared `AsyncSession` across concurrent database work was found, and no blind order-submit retry was found. No benchmark numbers were added.

## Implemented / unverified

- Search hover was not exercised in a rendered browser. Ports 8000 and 5173 were left running and were not restarted. No sign-in was attempted.
- Fullscreen Escape priority, reduced motion, and resize were not clicked through in a browser. The CSS and existing fullscreen unit test cover the layout class.
- `test_portfolio_endpoints_and_close` accepts 400 or 503 when the live quote is dark and then returns. On this run the file passed, which includes that branch or a real fill. A close round-trip against a live quote was not separately confirmed.
- `GET /market/session` and `GET /scan/recent` have no dedicated HTTP test. The login tests cover the calendar helpers they share.

## Blocked

- `telegraf.zip` and `APEX TRADING.zip` were not found under Downloads, Desktop, this repo, or Cursor assets. Fonts were not self-hosted and logos were not remapped. Loose Telegraf `.otf` files exist on the Desktop and were not treated as those zips. The site mark remains `frontend/public/brand/apex-logo.png`.
- TradingView pan/zoom cannot be read from the cross-origin iframe. `visibleBars` is the host-width slice of the loaded series, not an exact screenshot of the iframe. Studies were not removed. See the comment at the top of `frontend/src/chartCapture.ts`.

## Tests run

```
backend/.venv/bin/python -m pytest \
  backend/tests/test_fill_authenticity.py \
  backend/tests/test_otp_market_session.py \
  backend/tests/test_portfolio.py \
  backend/tests/test_apex_four_legs.py \
  backend/tests/test_expiry_close.py \
  backend/tests/test_stock_leg.py \
  backend/tests/test_change12_order_message.py \
  backend/tests/test_change12_3c.py \
  backend/tests/test_ws.py \
  backend/tests/test_login_email_code.py \
  backend/tests/test_login_single_email.py \
  backend/tests/test_security.py \
  backend/tests/test_executability.py \
  -q --tb=line
```

Result: **123 passed**, 1 warning, 41.09s.

```
cd frontend && npm run test -- \
  src/components/ChartOverlay.test.tsx \
  src/pages/quoteSourceLabel.test.ts \
  src/pages/HomeDashboard.test.tsx \
  src/pages/Login.test.tsx \
  src/pages/Dashboard.fullscreen.test.tsx \
  src/api.session.test.ts
```

Result: **6 files, 17 tests passed**, 969ms.

## Left alone

- `backend/app/services/otp.py` (shared `OtpCode` hash, commit `4ea90be`)
- `backend/app/services/signup_email.py`
- uvicorn on port 8000 and the frontend on port 5173 (not restarted)
- `docs/handoff/` and the untracked `telegraf/` directory (not part of this commit)
