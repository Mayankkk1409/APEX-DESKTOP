# APEX Desktop � Shared Contract

Source of truth for API types, Deep Scan layers, and environment variables.
Derived from:

- `APEX_Options_Platform_Full_Document.pdf` (v2.0, June 2026)
- `Project APEX.pdf`
- `Feature.pdf`

Do not invent layers. Do not invent legal language.

## Deep Scan layer order (exact)

Order follows Full Document �3.5 scan progress, with **Volume** inserted after Technical
(Project APEX 10-layer TA list) and **Risk Review** appended (user product spec + Feature F-038).

| # | Enum | Slide |
|---|------|--------|
| 1 | `technical` | Captured chart snapshot + pattern/trend overlays |
| 2 | `volume` | Accumulation/distribution, spikes, vs average |
| 3 | `candlestick_patterns` | Hammer, engulfing, stars, doji, continuation, indecision |
| 4 | `macd` | 12/26/9 live values, cross, histogram, divergence |
| 5 | `rsi` | 14-period live value, 70/30, divergence |
| 6 | `ema` | Stack 9 / 21 / 50 / 100 / 200, alignment, golden/death cross |
| 7 | `supertrend` | ATR length 10, factor 3 � server-side |
| 8 | `bollinger` | 20 SMA, 2 SD � width, squeeze, W/M patterns |
| 9 | `pivot_points` | PP, R1�R3, S1�S3 |
| 10 | `support_resistance` | Volume-cluster / 52-week nodes |
| 11 | `options_chain_greeks` | Full chain ladder (bid/ask, spread %, last, change, volume, OI, V/OI, IV, all Greeks) + per-contract �5 gate verdicts |
| 12 | `volatility` | IV vs HV, IVR, inversion |
| 13 | `sentiment` | News NLP, flow, social, put/call |
| 14 | `fundamentals` | EPS, P/E, revenue, analyst consensus, calendar |
| 15 | `strategy` | Composite score + playbook selection |
| 16 | `risk_review` | Thesis checkbox + order review |

Layer 11 is one slide, not two: Full Document �5 is a single section ("OPTIONS CHAIN ANALYSIS &
GREEKS ENGINE"), and a strike's liquidity gates only mean something read next to its Greek
verdict. The scan carousel therefore shows
`technical ? options_chain_greeks ? volatility ? sentiment ? fundamentals ? strategy ? risk_review`.

## Indicator parameters (from docs)

- EMA stack: **9 / 21 / 50 / 100 / 200**
- MACD: **12-period EMA, 26-period EMA, 9-period signal**
- RSI: **14-period**
- SuperTrend: **ATR length 10, factor 3**
- Bollinger Bands: **20 SMA, 2 standard deviations**
- Pivot: `PP = (H+L+C)/3` with R1�R3 / S1�S3 as documented

## Account modes (server-enforced)

- `paper_funded` � may include `starting_balance` (presets 10000 / 25000 / 50000 / 100000 or custom)
- `real_brokerage` � **must reject** `starting_balance` in request schema and handler. Frontend **unmounts** the field.

## Auth

- Login: username + password + 6-digit OTP
- OTP: Redis, TTL 90s, single-use, previous codes invalidated on new request
- JWT access token in memory; refresh token in httpOnly cookie
- `AUTOFILL_2FA=true` (non-production): mint a fresh OTP and return `code` for **every** user on each `/auth/otp/request` (paper and real). Production always disables autofill.

## Env vars (names only)

See `/.env.example`. Secrets load exclusively from environment.

## Burned key

A paper Alpaca key ID was pasted in chat. Treat it as burned.
Rotate in the Alpaca dashboard before any production use. Never commit key material.
See README for the rotation reminder.
