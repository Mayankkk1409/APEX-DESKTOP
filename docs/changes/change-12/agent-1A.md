# Change 12 — agent 1A (A2 session refresh)

Branch `change12/1A`, worktree `/Users/Mayank/Desktop/APEX-change12-1A`, started from `change12/base` at `d014ef6`. `backend/app/contracts.py` was not edited.

## Root causes

On `change12/base` (`d014ef6`):

- `backend/app/config.py:27` sets `access_token_ttl_seconds = 900`. PyJWT rejects that token at `exp` (`backend/app/security.py` `decode_token`). `backend/app/deps.py:28` turns that into HTTP 401 `Invalid access token`.
- The spec's QA note is three forced logouts in about 75 minutes with that error. This change did not re-time a live 75-minute session. What the code does is checkable: an access token dies after 900 seconds, and the client treated that 401 as logout. 75 minutes contains five of those windows, so repeated `Invalid access token` logouts during a session of that length follow from the missing refresh, not from a second timer.
- `frontend/src/api.ts:16-20` kept the access token in a module variable. A reload drops it. `frontend/src/api.ts:49-55` cleared that variable on every 401 and assigned `/login`. Nothing in the frontend called `POST /auth/refresh`.
- `frontend/src/App.tsx:17-19` (`Guard`) redirects when `getAccessToken()` is empty. That file is not owned here. Reload of `/app`, `/scan`, `/portfolio`, or `/settings` therefore hit `/login` before any cookie restore. `frontend/src/pages/Login.tsx:42-47` then wiped the in-memory user on mount.
- `backend/app/routers/auth.py:44-53` already set `HttpOnly` and `SameSite=Lax`, but `Secure` only when `app_env == production`. Dev and the Vite origin run over `http://127.0.0.1`, so the cookie was not marked `Secure`.
- The scan lived only in the Zustand store (`frontend/src/store.ts`). `window.location.assign("/login")` on 401 reloaded the document and dropped symbol, expiry, bars, and the recommendation.

## Changes

Refresh token cookie (`backend/app/routers/auth.py:44-63`, `backend/app/config.py:32-37`):

- `HttpOnly`, `Secure` (default on in development, staging, and production), `SameSite=Strict`, `Path=/`, `Max-Age` equal to the existing 7-day refresh TTL (`604800`). Logout deletes the cookie with the same `Secure`, `HttpOnly`, `SameSite`, and `Path`. Starlette 1.6.0 `delete_cookie` defaults `secure` to false, which would not match the cookie that was set.
- `POST /auth/refresh` requires `typ=refresh`, a live unrevoked `jti` for that user, and a DB expiry still in the future (`auth.py:254-275`). The same refresh cookie is reused until logout or its own expiry. Rotating it on every silent refresh lets a second in-flight call present the old cookie, receive 401, and clear the cookie the first call just stored.
- The JSON body still returns only the access token, plus `expires_in` (900) and `refresh_in` (840). The refresh token is not in the body.

Client (`frontend/src/api.ts`):

- Access token stays in memory. `setAccessToken` schedules `POST /auth/refresh` `refresh_in` seconds after issue (840s, which is 60s before the 900s expiry). A 401 on an authenticated call refreshes once and retries. A 401 from login, OTP, or the refresh call itself does not loop. A rejected refresh clears the memory token and sends the user to `/login`.
- `restoreSession()` is the reload path: no memory token, cookie still present.
- No access or refresh token is written to `localStorage` or `sessionStorage`.

Scan (`frontend/src/store.ts:6-66`, `170-190`):

- Symbol, timeframe, expiry, recommendation, snapshot, and captured bars are written to `sessionStorage` key `apex_scan_session`. That payload has no token fields. `setUser` does not clear them, so a successful refresh leaves the scan in place. A full reload reads them back. Explicit logout calls `clearScanSession()` (`LogoutButton.tsx`).

Reload routing (`frontend/src/pages/Login.tsx`):

- `/login` tries `restoreSession()` before showing the form. On success it returns to `state.from` when that path is `/app`, `/scan`, `/portfolio`, or `/settings`.

Dev proxy (`frontend/vite.config.ts`, `frontend/src/lib/devProxy.ts`):

- API prefixes use `changeOrigin` and `cookieDomainRewrite: ""` so `Set-Cookie` is stored for the Vite host. `proxyReq` copies the browser `Cookie` header onto the upstream request.

Access-token lifetime is unchanged at 900 seconds. Refresh lifetime is unchanged at 604800 seconds. Spread, OI, and staleness thresholds were not touched.

## Tests

Backend, from `backend/`:

`backend/.venv` from the main checkout, against this worktree:

`1492 passed, 59 skipped, 0 failed` (27.78s), plus the existing `StarletteDeprecationWarning` in `tests/test_ws.py`. Baseline on `change12/base` was `1482 passed, 59 skipped, 0 failed`. The 10 new tests are 6 in `backend/tests/test_session_refresh.py` and 4 in `backend/tests/test_security.py`.

- Simulated 2-hour session: eight expired access tokens (8 × 900s). Each `/auth/me` returns 401 `Invalid access token`, `POST /auth/refresh` with the same cookie returns 200, and the new access token reads `/auth/me`.
- Reload: `POST /auth/refresh` with only the cookie (no `Authorization` header) returns 200. The new access token then gets 200 from `/auth/me` (`/app` and `/settings`), `/api/portfolio` (`/portfolio`), and `/scan/layers` (`/scan`).
- Expired access token on `POST /scan` is 401 `Invalid access token`, then refresh, then the same AAPL snapshot and expiry returns 200 with `symbol` AAPL.
- Logout `Set-Cookie` has `Max-Age=0`. The next refresh with that jar is 401.
- An access token presented as the refresh cookie is 401.
- Cookie on OTP verify is `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, and is not the access token. The body has `expires_in` 900 and `refresh_in` 840, and no `refresh_token`. This runs with `APP_ENV=development`.
- `decode_token` rejects an expired access token with `ExpiredSignatureError`, rejects a refresh token presented as an access token, and the access and refresh lifetimes stay 900s and 604800s.

Frontend (`vitest`, files touched):

`9 passed` across `src/api.session.test.ts` (4), `src/pages/Login.test.tsx` (3), `src/lib/devProxy.test.ts` (1), `src/store.session.test.ts` (1).

- Fake timers: a token with `refresh_in` 840 refreshes 8 times across 120 minutes, `location.assign` is not called, and `localStorage` does not receive the access token.
- `restoreSession()` after a null memory token, and `pathAfterSessionRestore` for `/app`, `/scan`, `/portfolio`, and `/settings`.
- `api.scan` gets 401 `Invalid access token`, refreshes, retries, and the Zustand scan fields are unchanged.
- A 401 from `/auth/refresh` clears the memory token and assigns `/login`.
- Scan sessionStorage round-trip does not contain `access_token` or `refresh_token`.

Full frontend `vitest run`: `285 passed, 5 failed`. The 5 failures are all in `frontend/src/pages/DeepScan.order.test.tsx` (`ticketTypeLabel` and `buildOrderReview` are not defined). That file is unchanged from `d014ef6` and is owned by 1D. The session tests above are not in that file.

No browser pass. This session had no browser automation tool. Cookie flags and the refresh loop were checked through the API suite and vitest, not in Chrome.

## Sources

- PyJWT current usage, Expiration Time Claim: `jwt.decode` verifies `exp` against UTC and raises `ExpiredSignatureError`. https://pyjwt.readthedocs.io/en/stable/usage.html#expiration-time-claim-exp (fetched 2026-10-05). The access token still uses that `exp` claim. The client refreshes before it; the server does not accept an expired access token.
- MDN `Set-Cookie`: `HttpOnly` hides the cookie from `document.cookie` but the browser still sends it on `fetch`. `Secure` is sent only on `https`, except that the `https` requirement is ignored for localhost. `SameSite=Strict` is same-site requests only. `SameSite=None` requires `Secure`. https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie (fetched 2026-10-05).
- OWASP Session Management Cheat Sheet: session cookies must set `Secure` and `HttpOnly`, and must set `SameSite=Strict` (preferred) or `SameSite=Lax`. Do not store access tokens, refresh tokens, or JWTs in `localStorage` or `sessionStorage`. https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html (fetched 2026-10-05).
- Vite `server.proxy` extends http-proxy, including `cookieDomainRewrite` (empty string clears `Domain`). https://vite.dev/config/server-options.html#server-proxy (fetched 2026-10-05). The installed Vite type comment says `cookieDomainRewrite` rewrites the domain of `Set-Cookie` headers.
- Starlette 1.6.0 `Response.set_cookie` / `delete_cookie` (installed `starlette/responses.py`): `secure` defaults to false and `samesite` defaults to `lax`. Logout passes the same flags used at set time.

`SameSite=Strict` is the OWASP preference, not a guess. The dev app proxies API calls on the Vite origin, so the refresh `POST` is same-site and the cookie is sent. MDN's localhost exception is why `Secure` is on for `http://127.0.0.1` as well as production.

## Open questions

- The access token is still in JavaScript memory so `Authorization: Bearer` keeps working (`deps.py` `HTTPBearer`). It is not in `localStorage` or `sessionStorage`. OWASP prefers an `HttpOnly` cookie for session credentials. Moving the access token into a cookie would change every authenticated call and the tests other agents own. Not done here.
- OWASP also recommends the `__Host-` cookie prefix (`Secure`, `Path=/`, no `Domain`). The cookie name is still `apex_refresh`. Renaming it is a follow-up.
- `COOKIE_SECURE` and `COOKIE_SAMESITE` are settings. Defaults are `true` and `strict`. `COOKIE_SAMESITE=none` is rejected unless `Secure` is on. `COOKIE_SECURE=false` would turn `Secure` off. Nothing in this change sets that.
- The chart image is not copied into `sessionStorage` (it can be large). Symbol, expiry, bars, snapshot, and the recommendation are.

## Requests for other owners

- `frontend/src/App.tsx` (no Phase 1 owner). `Guard` (`getAccessToken()` at the lines that were 17-19 on `d014ef6`) redirects to `/login` before `restoreSession()` resolves. Login restores the cookie and navigates back, so the session survives, but the address bar passes through `/login`. Please await `restoreSession()` from `frontend/src/api.ts` before `Guard` chooses a route, and do not clear the scan fields in `store.ts` when that call succeeds.
- `frontend/src/pages/Dashboard.tsx` (1B) and `frontend/src/hooks/useMarketSocket.ts` (not in the plan). The socket URL is fixed from `getAccessToken()` for the life of that render. `api.ts` now exports `subscribeAccessToken`. After 15 minutes the query token expires. `backend/app/routers/ws.py` closes that socket with `4401`, and `frontend/src/lib/marketSocket.ts` treats `4401` as terminal, so it will not reconnect. The HTTP session stays logged in. Please resubscribe with the new memory token. Do not put the token in `localStorage`.
- `frontend/src/lib/brokerageApi.ts` (not in the plan) has its own `fetch`. It does not call the silent refresh in `api.ts`. A 401 on a brokerage call will not retry. Please send those calls through `api.ts` or call the same refresh helper.
