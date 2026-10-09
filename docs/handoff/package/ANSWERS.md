# Answers

Branch `change12/base`. Each answer keeps three facts apart: what the code does today, what the owner decided, and what is not built. Citations are files read for this package. A parallel edit of OTP verify, mail, auth, and market-session tests was in progress and was not treated as shipped.

## 1. Project copy

What the code is: the checkout has `frontend/`, `backend/` (including `backend/alembic/`), `docs/`, `infra/`, `frontend/package.json`, `frontend/package-lock.json`, `backend/requirements.txt`, a root `package.json`, `docker-compose.yml`, `README.md`, `.env.example`, and `.cursor/rules/apex-encyclopedia-strategy.mdc`.

What the owner decided: a Drive copy or a zip is acceptable when it excludes `.env`, database files, journals, `node_modules`, and `.venv`.

What is not built: this answer is not a second copy of the source. The zip for that decision is `APEX-DESKTOP-source.zip` next to this file.

## 2. Screens

What the code does today: `frontend/src/App.tsx` shows `Splash` once on `/` (`splashSeen` is false and the path is `/`), then routes `/` to `/login`. Public routes are `/login` (`Login`) and `/signup` (`Signup`). Signed-in routes are `/app` (dashboard; the chart is on this page), `/scan` (`DeepScan`, with the dashboard kept mounted and hidden), `/portfolio`, and `/settings`. Any other path redirects to `/`. `frontend/index.html` titles the tab `APEX Desktop` and defaults the theme to dark unless `apex_theme` in localStorage says otherwise. The code does not name a browser. There is no mobile route. `frontend/src/index.css` restacks some blocks under 720px and 900px. The chart host `.tv-host` has `min-height: 42rem`.

What the owner decided: describe the screens that exist, and do not invent an equity day-trade view.

What is not built: an equity day-trade screen, an Options/Equity toggle, and a mobile shell. Screenshots of the dashboard, the options scan, and the chart were not taken. Splash and login images in `screenshots/` were captured from the server already listening on `http://127.0.0.1:5173/` without signing in. Signup was not captured. A recording was not captured.

## 3. Equity and options

What the code does today: there is no equity day-trade view and no Options/Equity control. The only view switch found is Paper Trading versus Connected Brokerage in `frontend/src/components/BrokerageConnectionPanel.tsx`, stored as `portfolioViewMode` (`paper` or `brokerage`) by `readPortfolioViewMode` in `frontend/src/lib/portfolioViewMode.ts`. The word equity still appears as account value, as the portfolio value chart `data-chart-engine="apex-equity"` in `frontend/src/components/PnlChart.tsx`, and as the position label from `assetLabel` in `frontend/src/lib/portfolioFormat.ts` (`us_equity` becomes `Equity`, `us_option` becomes `Option`).

What the owner decided: equity mode was removed. Do not preserve a ticker across an equity/options switch.

What is not built: that switch, and any transition into or out of an equity trading screen.

## 4. Dashboard hover

What the code does today: the dashboard is `/app`, rendered by `Dashboard` in `frontend/src/pages/Dashboard.tsx`. Search rows use the class `ticker-hit`. In `frontend/src/index.css`, `.ticker-hit:hover`, `.ticker-hit:focus`, `.ticker-hit:focus-visible`, and the keyboard-selected option set a gold left border (`border-left-color: var(--apex-gold)`), full opacity, and background `var(--apex-row-hover)`. Watchlist rows are plain buttons inside `[data-testid="watch-list"]`. No CSS rule targets that list on hover.

What the owner decided: stock rows should be highlighted in search and in watchlists.

What is not built: a watchlist hover highlight. The search highlight is the rule above. The dashboard itself was not captured.

## 5. Chart fullscreen and scroll

What the code does today: `TradingViewChart` in `frontend/src/components/TradingViewChart.tsx` renders a button labeled `Enter chart fullscreen` or `Exit chart fullscreen`. Its click calls `onFullscreenToggle`. `requestChartFullscreen` in `frontend/src/pages/Dashboard.tsx` toggles React state `chartFull`, which adds the class `desk--chart-full` on the desk. No `requestFullscreen` call exists in the frontend. `.desk--chart-full` in `frontend/src/index.css` sets the desk to `height: 100dvh`, `max-height: 100dvh`, and `overflow: hidden`, and lets the chart slot fill that box. Brand, header tools, and the folded regions lose pointer events. Entering this mode scrolls the window to the top. Leaving it restores the saved scroll position. Escape calls `requestChartFullscreen(false)` unless the ticker menu, a position certificate, or the connect modal is open. There is no wheel listener on the dashboard chart. `.tv-study-overlay` is `pointer-events: none`, so the wheel goes to the TradingView iframe (`.tv-host iframe`). Outside this mode, page scrolling is unchanged. Inside it, the desk does not scroll because of `overflow: hidden`.

What the owner decided: report that behavior. No separate fullscreen preference was stated for this package.

What is not built: the browser Fullscreen API on this control. The chart screen was not captured.

## 6. Visual direction

What the code does today: `frontend/src/index.css` sets the default background `--apex-bg` to `#07070a` and the gold accent `--apex-gold` to `#c4a56a`. A light theme exists under `html[data-theme="light"]`. The logo file the UI loads is `frontend/public/brand/apex-logo.png`.

What the owner decided: the visual direction is that dense dark terminal, and the logo file is that PNG.

What is not built: a Canva redesign, an SVG wordmark, and separate light and dark logo files.

## 7. OTP

What the code does today: brokerage routes and order routes do not call `verify_otp`. SnapTrade connect does not use it. `login` in `backend/app/routers/auth.py` (`POST /auth/login`) checks the username and password. If `_verified_since_open` is true, the response has `otp_required: false` and an access token. Otherwise `_email_login_code` stores a code with `claim_login_code` and `send_login_code` mails it. The response then has `otp_required: true` and no access token. The sign-in page calls `api.otpVerify` (`frontend/src/pages/Login.tsx`), which posts to `POST /auth/otp/verify`. `otp_verify` calls `verify_otp` in `backend/app/services/otp.py`. That function reads the Redis key `otp:{username}` and compares a hash. `claim_login_code` writes that same key. A failed check raises `Invalid or expired code`. `frontend/src/lib/apiError.ts` maps that text to the title `Code not accepted` and the sentence `That code is invalid or expired.` The emailed code is 6 digits (`generate_otp` in `backend/app/security.py`), hashed, and kept for 600 seconds (`LOGIN_CODE_TTL_SECONDS` in `auth.py`). A second login within 45 seconds reuses it and does not send another email. `POST /auth/login/code` replaces it. `.env.example` names `OTP_TTL_SECONDS` for `issue_otp`, which password recovery and `POST /auth/otp/request` use. That is not the emailed login-code TTL. Password recovery (`POST /auth/forgot-password` and `POST /auth/forgot-password/verify`) uses the same Redis key, issues a session, and does not write `otp_devices`. It is still APEX account access.

What the owner decided: OTP is for APEX login only, not broker connection and not trade authorization. The owner also reports that the screen says `Code not accepted. That code is invalid or expired.` even for the correct emailed code.

What is not built: this package does not claim that rejection is fixed. A parallel change is editing the verify path. This note did not log in and did not submit a code.

## 8. Device, weekends, holidays, and the open

What the code does today: `otp_devices` in `backend/app/models/otp_device.py` is unique on `user_id` and `device_id`. `login` sets an httpOnly cookie `apex_device` (`_bind_device` in `auth.py`): signed `device_id.mac`, `Secure` from settings (default true), `SameSite` from settings (default `strict`), max age 400 days. `_verified_since_open` skips the code only when `otp_verified_at` is at or after `getLastMarketOpen(now)`. `getLastMarketOpen` in `backend/app/services/market_session.py` walks backward to the latest weekday that is not in the hardcoded NYSE holiday set and whose 9:30 `America/New_York` is at or before `now`. Saturday, Sunday, a listed holiday, and the time before 9:30 on a trading day therefore use the previous session’s 9:30. A verification after that earlier open still skips the code until the next session’s 9:30. The clock is the server’s timezone-aware `now`.

What the owner decided: verification does not carry across closed days. Friday does not cover Saturday or Sunday. Saturday does not cover Sunday. Sunday does not cover Monday. On a trading day, a code entered before 9:30 `America/New_York` does not cover times at or after 9:30. After 9:30, the same device skips the code for the rest of that calendar day. Holidays match weekends: that calendar date only. Per device still depends on `otp_devices` plus the httpOnly cookie, which the code does implement.

What is not built: the closed-day rule above is not what `getLastMarketOpen` does today. A parallel change is updating the app. This package does not describe that change as shipped.

## 9. Known issues

What the code does today: commit `c3d6457` removed the 30-second `asyncio.wait_for` around the sign-in SMTP send in `send_login_code`. Before that, a timeout returned false, and `_email_login_code` in `auth.py` then called `invalidate_login_code`, which deletes the code just stored by `claim_login_code`. The sign-in screen copy for a rejected code is the sentence in section 7. No efficiency audit was run for this package.

What the owner decided: record the mail fix that is in `c3d6457`, record the reported “code not accepted” failure, and do not invent slow screens, costs, or other errors. Delivery for that mail commit returned 250 to the account address. A mailbox was not opened for this package.

What is not built: an efficiency audit. The invalid-code fix is not claimed done.

## 10. Paper, live, and tests

What the code does today: `Settings.alpaca_trading_mode` in `backend/app/config.py` defaults to `paper`. `.env.example` sets `ALPACA_TRADING_MODE` to `paper`. `resolved_broker_base_url` uses `https://paper-api.alpaca.markets` when `ALPACA_BROKER_BASE_URL` is empty and the mode is not `live`. `live` uses `https://api.alpaca.markets`. Data defaults to `https://data.alpaca.markets`. `backend/app/routers/health.py` reports the options feed as `indicative` unless the mode is `live` and Alpaca keys are present, in which case it reports `opra`. Signup rejects `starting_balance` for `real_brokerage` in `signup` (`auth.py`). `notices_from_external` in `backend/app/services/expiry_close.py` says SnapTrade and any other read-only book are alert-only and never closable there. The settings toggle “Global auto-execution” starts `false` in `DEFAULT_USER_SETTINGS` (`frontend/src/lib/userSettings.ts`). `api.syncSettings` posts the score minimum, risk profile, max risk, max positions, and theme to `PATCH /api/settings/trading`. That body does not include `autoExecEnabled`.

What the owner decided: Alpaca paper is the default path. SnapTrade read-only is not paper-filled, which matches the expiry-close comment above.

What is not built: this package did not run `backend/.venv/bin/python -m pytest` or `cd frontend && npm run test`. Both commands exist. `backend/.venv/bin/python` is on disk. The frontend script is `vitest run`.
