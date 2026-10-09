# Setup

Facts below are from files in this repo. Variable names come from `.env.example`. No values are listed. This note did not run the test suite.

## Layout

`frontend/package.json` and `frontend/package-lock.json` are the UI dependencies. `backend/requirements.txt` is the API dependencies. There is no `pyproject.toml`. The root `package.json` lists `html2canvas` and `lightweight-charts` and has no scripts. `backend/alembic/` and `backend/alembic.ini` are present. `docker-compose.yml` and `README.md` are at the repo root.

## Environment names

Copy `.env.example` to `.env` locally. Do not commit `.env`.

Names in `.env.example`: `APP_ENV`, `APP_SECRET_KEY`, `APP_CORS_ORIGINS`, `LOG_LEVEL`, `SENTRY_DSN`, `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS`, `OTP_TTL_SECONDS`, `AUTOFILL_2FA`, `DATABASE_URL`, `REDIS_URL`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_TRADING_MODE`, `ALPACA_BROKER_BASE_URL`, `ALPACA_DATA_BASE_URL`, `ALLOW_OPTIONS_SIMULATOR`, `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENV`, `SNAPTRADE_BASE_URL`, `ENCRYPTION_KEY`, `API_PUBLIC_BASE_URL`, `FRONTEND_BASE_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`, `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_SPLASH_DURATION_MS`, `THETA_FILTER_MODE`, `THETA_MAX_PCT_PER_DAY`, `ENTRY_COMPOSITE_MIN`, `EXIT_COMPOSITE_MIN`, `MIN_IV_INVERSION_PTS`, `RULE1_DELTA_MIN`, `RULE1_DTE_MIN`, `RULE1_DTE_MAX`, `RULE1_THETA_PCT_PER_DAY`, `RULE1_DELTA_THETA_RATIO_MIN`, `RULE1_SPREAD_MAX`, `RULE1_SENTIMENT_BULL_MIN`, `RULE1_SENTIMENT_BEAR_MAX`, `RULE2_IV_RANK_MIN`, `RULE2_RSI_MIN`, `RULE2_RSI_MAX`, `RULE2_SHORT_DELTA_MAX`, `RULE2_DTE_MIN`, `RULE2_DTE_MAX`, `RULE2_WING_WIDTH_PCT`, `RULE2_SPREAD_MAX`, `RULE2_CREDIT_MIN_PCT_OF_WIDTH`, `GAMMA_EARNINGS_DAYS_MIN`, `GAMMA_EARNINGS_DAYS_MAX`, `GAMMA_FRONT_IV_RANK_MIN`, `GAMMA_FRONT_BACK_IV_RATIO_MIN`, `GAMMA_HISTORY_HITS_MIN`, `GAMMA_HISTORY_LOOKBACK`, `GAMMA_ADV_MIN`, `GAMMA_OPEN_INTEREST_MIN`, `GAMMA_SPREAD_MAX`, `GAMMA_BACK_WEEK_DAYS`, `GAMMA_BACK_WEEK_TOLERANCE_DAYS`.

The SnapTrade names `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENV`, and `ENCRYPTION_KEY` appear twice in that file.

`backend/app/config.py` uses SQLite when `DATABASE_URL` is left at the code default. Sign-in codes need Redis (`REDIS_URL`).

## Frontend

`frontend/package.json` has `dev` (`vite`) and `test` (`vitest run`). `frontend/vite.config.ts` sets `host` to `127.0.0.1`, `port` to `5173`, and `strictPort` to true.

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Backend

`README.md` starts the API from `backend/` after a virtualenv exists and the root env file is loaded. `backend/.venv/bin/python` is present in this checkout.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source ../.env && set +a
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: `http://127.0.0.1:8000/health`.

## Tests

These scripts exist. This package did not run them.

```bash
backend/.venv/bin/python -m pytest
```

Run that from `backend/`, or pass the backend tests path.

```bash
cd frontend && npm run test
```

## Docker

`README.md` also documents `docker compose up --build` after `.env` exists. Compose is in `docker-compose.yml`.
