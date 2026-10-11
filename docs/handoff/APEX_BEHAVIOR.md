# APEX Desktop handoff

Branch: `change12/base`. Facts below are from the current code and `.env.example`. No secrets are included. Variable names only.

This is a paper-trading options terminal. Alpaca orders use paper mode unless `ALPACA_TRADING_MODE` is `live`. SnapTrade is an optional read-only brokerage connection. Do not describe this app as live auto-trading.

## 1. Folder structure

```
APEX DESKTOP/
├── frontend/          React + TypeScript + Vite (package.json, package-lock.json)
├── backend/           FastAPI (requirements.txt, pytest.ini, alembic/)
├── docs/
├── infra/
├── .env.example
├── docker-compose.yml
├── package.json       root lockfile only lists html2canvas and lightweight-charts
└── README.md
```

Frontend scripts live in `frontend/package.json`. Backend dependencies live in `backend/requirements.txt`. There is no `pyproject.toml`.

A full drive copy or ZIP is fine if it excludes `.env`, `*.db`, SQLite journals (`*-journal`), `node_modules`, and `.venv`. `.gitignore` already ignores `.env`, `*.db`, `node_modules`, and `.venv`. It does not mention journals. This handoff did not create a ZIP.

`.env.example` names (no values): `APP_ENV`, `APP_SECRET_KEY`, `APP_CORS_ORIGINS`, `LOG_LEVEL`, `SENTRY_DSN`, `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS`, `OTP_TTL_SECONDS`, `AUTOFILL_2FA`, `DATABASE_URL`, `REDIS_URL`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_TRADING_MODE`, `ALPACA_BROKER_BASE_URL`, `ALPACA_DATA_BASE_URL`, `ALLOW_OPTIONS_SIMULATOR`, `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENV`, `SNAPTRADE_BASE_URL`, `ENCRYPTION_KEY`, `API_PUBLIC_BASE_URL`, `FRONTEND_BASE_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`, `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_SPLASH_DURATION_MS`, plus the strategy-gate names in that file. The SnapTrade block is repeated later in `.env.example` (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENV`, `ENCRYPTION_KEY`). Example `ALPACA_TRADING_MODE` is `paper`. Example `ALLOW_OPTIONS_SIMULATOR` is `false`. Example `SNAPTRADE_ENV` is `sandbox`.

If those Alpaca URL overrides are empty, code uses `https://paper-api.alpaca.markets` for paper and `https://api.alpaca.markets` for `live`. Data defaults to `https://data.alpaca.markets`. The options feed is `indicative` in paper mode and `opra` in live mode when keys are present.

## 2. Screens

Routes in `frontend/src/App.tsx`:

| Path | What it is | Auth |
|---|---|---|
| `/` | Splash once (`Splash`), then redirect to `/login` | public |
| `/login` | Sign in, and password recovery on the same page | public |
| `/signup` | Sign up | public |
| `/app` | Dashboard. The chart is on this page, not its own route | signed in |
| `/scan` | Options deep scan (`DeepScan`). The dashboard stays mounted but hidden | signed in |
| `/portfolio` | Portfolio | signed in |
| `/settings` | Settings | signed in |

Any other path redirects to `/`.

There is no equity view and no Options/Equity toggle.

The page title is `APEX Desktop`. Default theme is dark (`index.html` sets `dark` unless `apex_theme` in localStorage says otherwise). A light theme exists.

The code does not name a browser. There is no mobile route or mobile shell. The desk is a large desktop layout (chart slot min-height `42rem`, ticker panel min-height `36rem`). Some scan cards restack under 720px and 900px. Use desktop Chrome or Safari.

`http://127.0.0.1:5173/` and `http://127.0.0.1:8000/health` both returned HTTP 200 on this machine. The browser tool could not keep a tab open, so this note does not describe a rendered splash, login, or signup page, and there is no screenshot or recording.

## 3. Equity / options transition

There is no switch. Current code has no equity day-trading mode and no transition into or out of one.

The only view control is Paper Trading vs Connected Brokerage (`portfolioViewMode`: `paper` or `brokerage`) in the brokerage panel. That is not an options/equity toggle.

The word “equity” still appears as account value (settings and the portfolio chart) and as an asset-class label (`Equity` vs `Option` on a position). Those are not an equity trading screen.

## 4. Dashboard

`/app` is the dashboard.

Search suggestions use the class `ticker-hit`. Hover, focus, and the keyboard-selected row set a gold left border, full opacity, and background `--apex-row-hover`.

Watchlist rows do not. They are plain buttons in `#watch-list` with no hover class and no matching CSS rule.

## 5. Chart fullscreen

The control is a button on the dashboard chart (`Enter chart fullscreen` / `Exit chart fullscreen`). It does not call the browser Fullscreen API. No `requestFullscreen` usage was found.

It adds the class `desk--chart-full` on the dashboard. That class sets the desk to `height: 100dvh`, `max-height: 100dvh`, and `overflow: hidden`, and lets the chart slot fill that box. Brand, header tools, stats, the daily summary, and the lower drawer fold away. Escape leaves this mode unless the ticker menu, a position certificate, or the connect modal is open. Entering it scrolls the window to the top; leaving it restores the previous scroll position.

Scrolling over the chart is not handled. There is no wheel listener on the dashboard chart. The study overlay has `pointer-events: none`, so the wheel goes to the TradingView iframe. Outside this expanded mode, page scrolling is unchanged. Inside it, the desk itself does not scroll because of `overflow: hidden`.

## 6. Visual direction

Dense dark trading terminal. Default background `#07070a`, gold accent `#c4a56a`.

The logo to use is `frontend/public/brand/apex-logo.png` (PNG, 800×800). `ApexLogo` and the favicon both load `/brand/apex-logo.png`. Install that file. It was not redesigned here. There is no SVG wordmark. The splash word “APEX” is HTML text next to that PNG.

## 7. OTP

The code is for APEX login only. Brokerage routes and order routes do not call `verify_otp`. SnapTrade connect does not use it.

Flow: `POST /auth/login` checks username and password. If this browser is already verified for the current NYSE session, the response has `otp_required: false` and an access token. Otherwise it emails a code and returns `otp_required: true` with no access token. The sign-in page then calls `POST /auth/otp/verify`.

A new code is required after each regular NYSE open at 9:30 `America/New_York`. `getLastMarketOpen` returns that open. Login skips the code only when `otp_devices.otp_verified_at` is at or after that open. The clock is the server’s timezone-aware `now`, not a timestamp from the client.

The emailed login code is 6 digits, stored hashed in Redis under `otp:{username}`, and expires in 600 seconds (`LOGIN_CODE_TTL_SECONDS` in `auth.py`). A second login within 45 seconds reuses that code and does not send another email. Resend (`POST /auth/login/code`) replaces it. `.env.example` `OTP_TTL_SECONDS=90` is the TTL for `issue_otp`, which password recovery and `POST /auth/otp/request` use. It is not the emailed login-code TTL.

Password recovery (`POST /auth/forgot-password` and `POST /auth/forgot-password/verify`) uses that same Redis OTP key. It is still APEX account access, not brokerage and not a trade approval. That verify path issues a session and does not write `otp_devices`.

## 8. Per device, weekends, holidays, before the open

Per device: yes. Table `otp_devices` is unique on `user_id` + `device_id`. Login sets an httpOnly cookie named `apex_device` (signed `device_id.mac`, `Secure`, `SameSite` from settings, default `strict`, max age 400 days). A missing, other, or forged cookie is a different device and must enter a code. Another user on the same cookie still must enter a code. Tests in `backend/tests/test_otp_market_session.py` cover this.

Weekends are not sessions. Saturday and Sunday use the previous session’s 9:30. The owner has decided otherwise, and a parallel change is updating the app; that new rule is not what `getLastMarketOpen` does in `backend/app/services/market_session.py` today.

Holidays are a hardcoded NYSE full-day list for 2024–2028 in `backend/app/services/market_session.py`, not a live calendar feed. A holiday uses the previous session’s 9:30. Early closes still open at 9:30. This note did not re-check every date against the exchange.

Before the open on a trading day, the last open is the previous session’s 9:30. A verification after that previous open still skips the code. At 9:30 or later, that previous verification no longer counts.

## 9. Known issues

Delivery was restored in c3d6457 and Gmail returned 250 to the account address; a mailbox was not opened for this package.

`send_login_code` sends through SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`). If `SMTP_HOST` or `SMTP_FROM` is empty, the send returns false and login responds 503 with “The sign-in code could not be sent.”

No other defects are listed. They were not observed for this note.

## 10. Paper vs live, and tests

Paper is the default. `.env.example` sets `ALPACA_TRADING_MODE=paper`, which selects `https://paper-api.alpaca.markets` when `ALPACA_BROKER_BASE_URL` is empty. `live` selects `https://api.alpaca.markets`. Missing Alpaca keys are supposed to yield empty market data, not fabricated quotes. `ALLOW_OPTIONS_SIMULATOR=true` is offline demo only.

Account modes are `paper_funded` and `real_brokerage`. Signup rejects `starting_balance` for `real_brokerage`.

SnapTrade (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENV`, `ENCRYPTION_KEY`) is optional. The service reads accounts, balances, positions, and orders, and can open a connection portal or disconnect. `expiry_close.py` states SnapTrade read-only accounts are never submitted.

The settings control “Global auto-execution (off by default)” starts `false` in localStorage (`apex_user_settings`). The browser save to `/api/settings/trading` sends the score minimum, risk profile, max risk, max positions, and theme. It does not send `autoExecEnabled`. `DeepScan.tsx` says that browser toggle is not a server gate.

Tests, from the repo root:

```bash
backend/.venv/bin/python -m pytest
```

Run that from `backend/`, or pass the backend path. `backend/.venv/bin/python` exists. This handoff did not run the suite.

```bash
cd frontend && npm run test
```

That script is `vitest run`.

## How to run

Backend, from `backend/`, after the venv exists and dependencies are installed:

```bash
cd backend
set -a && source ../.env && set +a
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite binds `127.0.0.1:5173` with `strictPort: true`. Open `http://127.0.0.1:5173`.

OTP needs Redis (`REDIS_URL`). The database default in code is SQLite if `DATABASE_URL` is unset. `.env.example` sets PostgreSQL.

## Not confirmed from a running UI

The rendered public pages were not seen. HTTP 200 only. No login was attempted.
