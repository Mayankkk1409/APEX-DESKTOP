# SnapTrade sandbox testing (read-only)

## Prerequisites

1. Create a SnapTrade developer account and obtain sandbox credentials.
2. Append to your local `.env` (never commit real values):

```env
SNAPTRADE_CLIENT_ID=your-client-id
SNAPTRADE_CONSUMER_KEY=your-consumer-key
SNAPTRADE_ENV=sandbox
ENCRYPTION_KEY=generate-a-32-byte-random-string
```

3. Install backend dependencies: `pip install -r backend/requirements.txt`
4. Run migration: `cd backend && alembic upgrade head`
5. Start backend (`uvicorn app.main:app --reload`) and frontend (`npm run dev`).

## Connect flow

1. Sign in to APEX and open the dashboard.
2. In **Live brokerage (read-only)**, click **Connect brokerage**.
3. Read the disclosure modal and click **Continue** — you will be redirected (full page) to SnapTrade's Connection Portal.
4. Choose a sandbox broker (e.g. Alpaca paper) and complete login/MFA.
5. SnapTrade redirects to `/api/brokerage/callback`, which syncs accounts and sends you back to `/?connected=true`.
6. Verify real balances, buying power, equity, day P&L (when available), positions, and last-synced timestamp appear.

## Refresh and disconnect

- **Refresh** calls live balance/positions endpoints and updates cached rows.
- **Disconnect** removes the read-only link for that account via SnapTrade and clears local cache. Paper trading is unchanged.

## Webhooks

Configure your SnapTrade dashboard webhook URL to:

`https://<your-api-host>/api/brokerage/webhook`

Events with a valid `Signature` HMAC header refresh cached holdings.

## Automated tests

```bash
cd backend && pytest tests/test_brokerage_encryption.py tests/test_brokerage_routes.py -q
cd frontend && npm test -- BrokerageConnectionPanel.test.tsx
```

## Scope check

This integration does **not** modify paper trading, order placement, charting, login/auth, or Deep Scan flows.
