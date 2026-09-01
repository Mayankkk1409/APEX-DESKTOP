# Encyclopedia Alignment Status

Last updated: 2026-08-31 (full 100-strategy playbook implementation).

## Confidence summary

| Area | Confidence | Notes |
|------|------------|-------|
| Strategy registry (100 strategies) | **High** | All tradeable entries have `payoff_function_ref`, leg specs, risk_type |
| Payoff calculators | **High** | 35 handlers in `payoffs/core.py`; 98/98 tradeable pass validator |
| Leg builders | **High** | `metrics_builder.py` dispatches all `strategy_id`s from chain snapshot |
| APEX Strategy strict gates | **High** | Unchanged — 4-leg builder + eligibility module |
| Strategy selectivity (one Best Match) | **High** | `strategy_recommendation.py` — undefined-risk excluded from auto-exec |
| Composite / options gates | **High** | Unchanged |
| Full 100-pattern TA taxonomy | **High** | `backend/app/analysis/ta/pattern_catalog.py` — 100 patterns / 12 families |
| 10-layer TA pipeline | **High** | `ta/pipeline.py` — MACD, RSI, EMA, SuperTrend, BB, candlestick, pivot/S-R, chart, volume, momentum |
| TA pattern surfacing | **High** | Confirmed H/M tier only (strength ≥ 65); max 3 chart highlights; EMA counter-trend down-weight |
| Frontend display fidelity | **High** | Unlimited max profit gated by `max_profit_unlimited_allowed`; backend patterns preferred via `resolveCatalysts()` |

## Technical analysis (encyclopedia — 2026-08-31)

- **100 patterns** in `backend/app/analysis/ta/pattern_catalog.py` across 12 families
- Detectors: `ta/detectors/candlesticks.py`, `charts.py`, `indicators.py`, `levels_gaps.py`
- **10-layer composite** in `ta/pipeline.py` with `layer_scores`, `layer_breakdown`, professional narrative
- Export rules: only **confirmed** H/M tier, strength ≥ 65, **max 3** for API/chart
- Bollinger squeeze scored neutral until volume-backed breakout; pivots/Fib = confluence context
- Harmonic patterns low-weight confluence only
- Frontend: `backendPatternsToCatalysts()` + `resolveCatalysts()` prefer scan API over local heuristics

## Full playbook implemented

All 100 registry strategies are wired:

- **98 tradeable** — leg builder + payoff handler + validator pass with mock AAPL chain (multi-strike front month + back month where required)
- **2 advisory** — `NO TRADE` entries; zero legs; always valid

### By family

| Family | Count | Status |
|--------|------:|--------|
| 1 — Single-leg directional | 10 | Implemented |
| 2 — Vertical spreads | 10 | Implemented |
| 3 — Straddles / strangles | 10 | Implemented |
| 4 — Calendars / diagonals | 10 | Implemented |
| 5 — Butterflies / condors | 15 | Implemented |
| 6 — Ratio / backspreads | 10 | Implemented |
| 7 — Stock-option combos | 10 | Implemented |
| 8 — Synthetic / conversion | 10 | Implemented |
| 9 — Volatility / advanced | 10 | Implemented |
| 10 — Income / no-trade | 5 | Implemented (2 advisory) |

## Production notes

### Verified (test-backed)

- Parametrized `test_all_100_strategies.py` — each `strategy_id` builds legs, computes payoff, passes `validate_strategy_output`
- Calendar / diagonal / APEX — dual-expiry chain required; blocked without back month
- Undefined-risk — payoff present; `tradeable=false`; auto-exec exclusion unchanged
- Stock combos — stock legs use ticker symbol; OCC check skipped for `side=stock`

### Honest limitations

1. **Dispersion trade** — single-underlying proxy; real dispersion needs index + component legs
2. **Married put/call** — option leg only in registry leg_count; stock position assumed
3. **Calendar/diagonal/APEX max profit** — IV-dependent; flagged `max_profit_iv_assumption_dependent`
4. **Ratio/backspread trap zones** — scanned numerically; undefined wing flagged

## Test coverage

- `backend/tests/test_technical_analysis_encyclopedia.py` — 100-pattern catalog, confirmation gating, EMA down-weight, Bollinger squeeze, composite breakdown, export cap
- `backend/tests/test_all_100_strategies.py` — 100 parametrized + fuzz sample
- `backend/tests/test_strategy_registry_validation.py` — regression safeguards
- `backend/tests/test_strategy_engine.py` — playbook selection
- Backend total: **397+ passed** (includes TA encyclopedia suite)

## Remaining gaps (non-strategy)

1. ~~Full 100-pattern TA backend detector~~ — **Done** (2026-08-31)
2. Composite weight UI grouping vs target weights
3. Live Alpaca dual-expiry verification on production symbols
4. Chart patterns needing extended bar history (cup & handle 50+ bars, golden cross 200 bars) may not fire on short capture windows — documented in detector `min_bars`
