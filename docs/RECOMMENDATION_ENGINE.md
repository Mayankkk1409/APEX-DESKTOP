# APEX Recommendation Engine

Deterministic rule-based strategy selection for Deep Scan. No LLM in the critical path — same inputs must yield the same Best Match.

Sources: Full Document §8–§10, Project APEX TA spec, `docs/CONTRACT.md`.

---

## Flow overview

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌─────────────┐
│ Market data │───►│ Regime detect│───►│ Hard gate filter│───►│ Composite    │───►│ Best Match  │
│ + TA layers │    │ IV/direction │    │ liquidity/risk  │    │ score        │    │ or No Trade │
└─────────────┘    └──────────────┘    └─────────────────┘    └──────────────┘    └─────────────┘
```

Implementation entry: `build_layers()` in `backend/app/services/scan_engine.py` → `select_strategy()` in `backend/app/services/strategy_engine.py`.

### Stage 1 — Regime detection

Inputs from the captured chart snapshot and options chain (never a different bar window):

- **Direction** — SuperTrend + MACD histogram → bullish / bearish / neutral.
- **IV environment** — IV vs HV, IV Rank, vol signal (`buy_premium` / `sell_premium` / `fair`).
- **Technical strength** — composite technical score from EMA alignment, SuperTrend, MACD, RSI bands.
- **Catalyst** — earnings alert from sentiment layer (5–10 day window for APEX Strategy).

### Stage 2 — Hard gate filter

Applied per contract via `backend/app/analysis/options_rules.py` and chain-wide in `build_chain_analysis()`:

| Gate | Rule |
|------|------|
| Bid/ask spread | Reject > 10% of mid (configurable, max 15%) |
| Open interest | ≥ 500 |
| Volume vs OI | Volume > 25% of OI |
| Buy delta | ≥ 0.50 (Rule 1: ≥ 0.55) |
| Sell delta | ≤ 0.20–0.25 |
| Δ/Θ ratio | > 10 for exceptional buys; < 3 for efficient sells |
| Gamma (7 DTE) | Flag unless APEX Strategy absorbs |
| Vega cap | Blocks long premium in catalyst unless override or APEX Strategy |
| Earnings | 1-day blackout (APEX Strategy exception) |
| Extreme IV | `iv > hv × 1.35` → stand aside |

Contracts failing hard gates are `rejected` or `screened_out`. Greeks Quality Score reflects the share of chain contracts that pass.

### Stage 3 — Composite score

Weighted sum (current production weights):

| Pillar | Weight | Source |
|--------|--------|--------|
| Technicals | 30% | EMA stack, SuperTrend, MACD, RSI |
| Volatility | 25% | IV/HV signal mapping |
| Options / Greeks | 20% | Clean-contract ratio on chain |
| Sentiment | 15% | News 40%, flow 35%, social 15%, P/C 10% |
| Fundamentals | 10% | P/E, EPS, revenue, calendar |
| Risk | 0% | Advisory; gates execution tier |

Formula (simplified):

```
composite = 0.30×tech + 0.25×vol + 0.20×greek + 0.15×sentiment + 0.10×fund
```

Explainable breakdown returned in the `apex_score` layer (`build_apex_score_layer()`).

**Execution tiers** (`backend/app/analysis/layers.py`):

| Score | Tier | Meaning |
|-------|------|---------|
| ≤ 50 | `blocked` | No trade |
| 51–71 | `caution` | Monitor; playbook shown for review only |
| ≥ 72 | `auto_exec` candidate | Full Document threshold met |
| ≥ 85 | Stretch target | Default user auto-exec minimum |

Penalties (target upgrade): pattern conflicts, stale quotes, wide spreads reduce effective score before tier assignment.

### Stage 4 — Strategy selection

`select_strategy()` applies Full Document §9.1 matrix:

1. Composite < 72 → **NO TRADE — Insufficient Conviction**
2. Extreme IV overhang → **NO TRADE — Wait for IV Crush**
3. Catalyst + rich front-week IV → evaluate **APEX Strategy** (strict module)
4. IV cheap → directional debit spreads, Benchmark Greeks, straddle, married structures
5. IV rich → iron condor, credit spreads
6. Fallback → diagonal or calendar by direction

Output: **one** `selected_strategy` in the strategy layer. UI label: **Best Match**.

Undefined-risk structures never receive `auto_exec` tier even when score is high.

---

## APEX Strategy qualification

Proprietary catalyst structure (formerly internal codename). User-facing name: **APEX Strategy** only.

All criteria must pass; otherwise return rejection reasons and fall through to the next eligible playbook.

| # | Criterion | Threshold |
|---|-----------|-----------|
| 1 | Catalyst timing | 5–10 calendar days to event |
| 2 | Front-week IVR | > 70 |
| 3 | Term structure | Front IV > back IV |
| 4 | Legs | 4: buy back-week call+put, sell front-week call+put at **same strikes** |
| 5 | Delta | 0.15–0.25 OTM on each wing |
| 6 | Offset | Front-week premium ≥ 50% of back-week debit |
| 7 | Stock ADV | > 5M shares |
| 8 | Per-strike OI | > 1,000 |
| 9 | Spreads | < 8% of mid on all four legs |

Structure absorbs the §5.4 gamma flag and satisfies the §5.3 vega cap in catalyst environments.

---

## Settings data model

User trading preferences (persisted per account):

```typescript
interface UserSettings {
  auto_execution_threshold: number;  // default 85, min meaningful 72
  auto_execution_enabled: boolean;     // default false
  risk_profile: "conservative" | "moderate" | "aggressive" | "custom";
  max_risk_per_trade_pct: number;
  max_open_positions: number;
  theme: "light" | "dark" | "system";
  spread_max_pct?: number;           // optional §5.5 override
}
```

Paper balance audit log:

```typescript
interface PaperBalanceAudit {
  previous_balance: number;
  new_balance: number;
  timestamp: string;   // ISO-8601
  reason: string;
}
```

Account deletion requires password confirmation and typed `DELETE` acknowledgment.

API surface (target):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/settings` | Read preferences |
| PATCH | `/api/settings` | Update risk/theme/auto-exec |
| PATCH | `/api/settings/paper-balance` | Reset simulated balance + audit |
| DELETE | `/api/account` | Delete account |

Frontend persists theme to `localStorage` immediately; syncs to backend when authenticated.

---

## Paper trading safeguards

- `paper_funded` accounts use user-chosen starting balance ($10k / $25k / $50k / $100k presets or custom). Default: $100,000.
- Balance edits are simulation-only; logged with prev/new/timestamp/reason.
- Orders route through Alpaca paper API or demo adapter — never touch real brokerage.
- UI shows **PAPER TRADE** banner on certificates and position modals.
- `real_brokerage` mode: no starting balance field; SnapTrade connections are read-only for portfolio display; orders require explicit brokerage authorization flow.

Day P/L baseline uses the chosen starting balance (`portfolio_pnl.py`), not a hardcoded $100k.

---

## Connecting brokerage and data providers safely

### Environment variables

All secrets load from `.env` (gitignored). Names only in `.env.example`:

| Variable | Purpose |
|----------|---------|
| `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` | Market data + paper execution |
| `ALPACA_PAPER_BASE_URL` | Paper trading endpoint |
| `SNAPTRADE_CLIENT_ID` / `SNAPTRADE_CONSUMER_KEY` | Real brokerage OAuth |
| `SNAPTRADE_ENCRYPTION_KEY` | Encrypt stored SnapTrade secrets |
| `DATABASE_URL` / `REDIS_URL` | Persistence + OTP |

Never commit key material. Rotate any key exposed in chat.

### Provider behavior

| Provider | Role | Missing-key behavior |
|----------|------|----------------------|
| Alpaca | Quotes, options chain, paper fills | Empty chain state; configure `.env` message |
| SnapTrade | Real account balances, positions, history | Connection panel shows setup prompt |
| Demo adapter | Offline development | Requires `ALLOW_OPTIONS_SIMULATOR=true` |

### Security practices

- JWT access in memory; refresh in httpOnly cookie.
- SnapTrade user secrets encrypted at rest (`snaptrade.py`).
- CORS restricted to `localhost:5173` in development.
- Real brokerage callback validates OAuth state token in Redis.
- Production: `APP_ENV=production`, `AUTOFILL_2FA=false`.

---

## Open position certificate API

Position detail endpoint should return everything the read-only certificate modal needs:

```typescript
interface PositionCertificate {
  ticker: string;
  strategy_name: string;       // "APEX Strategy" when applicable
  account_mode: AccountMode;
  entry_composite_score: number | null;
  score_breakdown?: ApexScoreBreakdown;
  current_pnl: number | null;
  greeks?: { delta; gamma; theta; vega };
  max_loss: number | null;
  max_profit: number | null;
  breakevens: number[];
  legs: Array<{
    symbol: string;
    side: "call" | "put";
    action: "long" | "short";
    strike: number;
    expiry: string;            // ISO date → format "Sep 18, 2026"
    qty: number;
    premium: number | null;
    fill_price: number | null;
  }>;
}
```

Reuse visual frame from `OrderConfirmationCertificate.tsx`. Order placement certificate must also show expiration per leg.

---

## Technical analysis gating (encyclopedia)

Pattern detection produces `PatternSignal` records. Only **confirmed** patterns above the strength floor reach API/chart overlays.

Confirmation requires evidence (volume spike, close beyond pattern boundary, indicator alignment). Counter-trend reversals against the EMA stack are down-weighted or suppressed.

10-layer TA weights feed the technical pillar of the composite score. Chart highlights use `chartHighlight.ts` / `ChartSnapshotOverlay` — strongest bull **or** bear conviction only.

---

## Testing checklist

Backend (`pytest`):

- Composite calculation and tier boundaries (50, 51, 72, 85)
- APEX Strategy rejection paths (each criterion independently)
- Undefined-risk exclusion from auto-exec
- Settings persistence and paper balance audit
- Account deletion flow
- "APEX Strategy" in API responses (not legacy name)

Frontend (`vitest`):

- Settings save/load and theme toggle
- Position click opens certificate with formatted expirations
- Best Match single-strategy display
- No Trade state when score < 60 (blocked tier)

---

## Related files

| File | Role |
|------|------|
| `backend/app/services/scan_engine.py` | Orchestrates layers |
| `backend/app/services/strategy_engine.py` | Playbook + composite breakdown |
| `backend/app/analysis/options_rules.py` | Per-contract gates |
| `backend/app/analysis/layers.py` | Threshold constants |
| `backend/app/services/options_analysis.py` | Chain analysis + execution tiers |
| `docs/CONTRACT.md` | Shared API/layer contract |
| `.cursor/rules/apex-encyclopedia-strategy.mdc` | Cursor session guidance |
