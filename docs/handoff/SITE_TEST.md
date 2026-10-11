# Site test

Date: 2026-10-09. Branch `change12/base`, commit `3ea29b8`. No commit and no push.

App `http://127.0.0.1:5173/` and API `http://127.0.0.1:8000` were already listening. Neither process was started again.

The in-IDE browser tab opened and then closed before a page could load. The walk below is system Chrome at 1440×900. Screenshots are files actually saved under `docs/handoff/package/screenshots/`.

## Verdict

Not ready.

The expiry reminder is a compact centered dialog in the browser, and its text body scrolls. The 24-hour sign-in skip is not fixed in the browser that was used: password submit showed the code screen, and a second login on that same browser was not completed.

## Automated tests

Backend `backend/.venv/bin/python -m pytest`: **1858 passed, 0 failed, 44 skipped**, 1 warning, 176.82s. Skipped tests were left in place.

Frontend `npm run test`: **361 passed, 0 failed, 0 skipped** (69 files, 4.31s).

## Confirmed

### Splash — pass

`http://127.0.0.1:5173/` showed the splash (`data-testid="splash"`), then the address became `/login`. Screenshot: `splash.png`.

### Login form — pass, then the code step failed

The form heading was “Sign in”, with username, password, Forgot password, Continue, and Create account. Screenshot: `login.png`.

Submitting the account password on this browser returned HTTP 200 with `otp_required: true` and no access token. The page then showed “Enter the sign-in code emailed to the address on this account.” Screenshot: `login-code.png`. That is a failed check. No code was typed on that attempt. `frontend/src/pages/Login.tsx` opens the code step unless `otp_required === false`. `backend/app/routers/auth.py` sets `otp_required` false only when this browser’s device cookie was verified inside 24 hours.

A later attempt on a new Chrome profile also got the code step. That profile had no saved device trust. After a letter from that submit was used, the desk opened. That does not clear the failed check above. The same browser was not taken through a second password login. Logout was covered by the expiry dialog (`docs/handoff/package/screenshots/failure.png`). The click target was `data-testid="expiry-login-hold"` in `frontend/src/components/ExpiryLoginGate.tsx`.

No “Email a new code” request was sent (`POST /auth/login/code` count was 0).

### Expiry reminder — pass for the populated book

After sign-in, “Expiring positions” / “Next 7 days” was on screen, with a PAPER TRADE banner. Viewport 1440×900. The card was 512×709, centered (center delta 0), top 96. It did not stretch to the viewport. The text body was 384px tall, `overflow-y: auto`, with scroll height 3386, so the copy scrolls inside the card. Screenshot: `expiry-reminder.png`.

Visible copy included the 16:00 America/New_York close sentence and one row at the top of the list: BAC, Short Iron Condor, Oct 16, 2026, strike 57, Call, Short, Settles “APEX auto-close”. Styles: `frontend/src/index.css` (`.expiry-login-card`, `.expiry-login-body`). Component: `frontend/src/components/ExpiryLoginCertificate.tsx`.

### Dashboard — pass

`/app` showed SPX, quote 7,765.36, change −36.41 (−0.47%). Balance 2,873,874.5, buying power 2,873,874.5, portfolio value 3,137,618. A “Connect brokerage” dialog was open on the first paint (`dashboard.png`). After Later, a banner read “Brokerage not connected — paper/demo data is active.” Search then showed AAPL at 340.43, +3.85 (+1.14%), and portfolio value 3,138,993.5 (`search.png`). No raw JSON. No horizontal overflow. Chart is the TradingView embed, not a JSON dump.

These figures are what the screen showed. They were not typed in by the test.

### Search — pass

Ticker search for AAPL offered “AAPL — Apple Inc.” The chart symbol changed from SPX to AAPL. Screenshot: `search.png`.

### Chart fullscreen — pass

Enter set `data-chart-fullscreen="true"` and the button label became “Exit chart fullscreen”. The chart slot was about 1171×821. Escape restored `data-chart-fullscreen="false"` and “Enter chart fullscreen”. Screenshot: `chart-fullscreen.png`.

### Options deep scan — pass, with a stale quote on the order step

Scan opened `/scan`. Technical slide showed an AAPL daily chart, 154 bars, 2026-03-02 to 2026-10-08 (`deep-scan.png`). Options chain greeks showed AAPL · 2026-10-09, calls and puts, and the line “76 of 152 Greeks filled locally where the vendor omitted them.” No raw JSON (`options-chain.png`).

Risk review stayed on `/scan`. It listed two option legs in sentences, composite 57.3, minimum 35.0, and “Not auto-executable: quote not current.” The thesis checkbox was visible. Place Trade was not. Screenshot: `risk-review.png`.

### Portfolio — pass

`/portfolio` rendered. Heading “Portfolio”. Unrealized P&L shown as $0. Sections for open positions, current portfolio, and order history were present. The equity chart area was still on a loading line when the shot was taken. No raw JSON. No horizontal overflow. Screenshot: `portfolio.png` (dark theme, low contrast in the capture).

### Settings — pass

`/settings` showed Account, Brokerage connection, and Risk & auto-execution. Cash and buying power 2,873,874.5, equity 3,137,618.5, total P&L “—”. Paper Trading account. Risk profile Moderate. Screenshot: `settings.png`. Appearance and Security were in the page tree below the fold; the shot does not show them.

## Not reached

### Second login on the same browser

Not done. The expiry dialog blocked Logout, so the 24-hour skip after a successful sign-in was not exercised. Do not treat the code screen on the first submit as proof that a trusted browser is prompted again. That second submit never happened.

### Empty expiry book

Not shown. This account has expiring positions, so the plain empty sentence was not on screen. The sentence “You have no open options expiring within the next 7 days.” is `EXPIRY_LOGIN_NONE` in `frontend/src/lib/expiryLoginNotice.ts`. `frontend/src/components/ExpiryLoginCertificate.test.tsx` expects it when the list is empty. That test passed with the suite. The browser did not show an empty book.

### Order confirm does not go to `/login`

No order was placed. Risk review did not offer Place Trade, and the quote was not current. Submitting that order would have been a guess, so it was left alone. The browser never left `/scan` for `/login` during the scan.

The fill path in code, not observed in the browser: a filled confirmation’s dismiss calls `refreshDeskQueries` and `nav("/app")` in `frontend/src/pages/DeepScan.tsx`. `frontend/src/pages/DeepScan.order.test.tsx` asserts those calls. `frontend/src/lib/deskRefresh.test.ts` asserts the book, daily P&L, and equity graph refresh together. `endSession` in `frontend/src/api.ts` is what assigns `/login`, and only after an auth failure.

## Other notes

Console during the walk: one 401 before sign-in, and one `net::ERR_TIMED_OUT`. No page exception. No raw JSON object in the visible text of dashboard, search, scan, portfolio, or settings.

`failure.png` is the expiry dialog sitting on top of the AAPL desk when logout was attempted. It is the same compact dialog, not a stretched page.
