# Validator Gap Analysis — Platform-Wide (2026-08-31)

## Executive summary

Trade-card defects (MSFT Short Iron Condor was the first reported case) stemmed from the validator checking leg *shape* and score bounds *when provided*, but not recomputing payoff from leg prices or enforcing quote monotonicity. IV Rank could surface out-of-band values because computation sites were not unified and `vol_layer` was not sanitized before display.

**Fix once for all:** a single universal validator (`strategies/validator.py`), a single IV Rank pipeline (`analysis/volatility.py` → `compute_iv_rank`), and hard score bounds at every computation source. All **98 implemented strategies** and the full test-matrix tickers (AAPL, MSFT, TSLA, NVDA, SPY + mock chains) are covered by `test_platform_trade_card_invariants.py`.

## Bugs and root causes (MSFT iron condor exemplar)

| Bug | Symptom | Root cause | Why validator missed (pre-fix) |
|-----|---------|------------|--------------------------------|
| **IV Rank 285.2** | Vol slide / scan showed 285.2 | Out-of-band value in `vol_layer`; proxy `(iv/hv)×40` or corrupted history not hard-failing at source | `_check_score_bounds` only ran on `scan_scores` passed to validator — not on raw `vol_layer` displayed elsewhere |
| **Credit / summary mismatch** | Legs sum to $0.13/share; card shows $0.14 credit | Payoff used pre-rounded net; `_finalize` rounded `net_debit_credit` independently of leg mids | No credit recomputation check |
| **Inverted put pricing** | SELL 492.5 @ $1.68, BUY 490 @ $1.73 | Stale/inconsistent chain quotes | No same-side premium vs moneyness gate |
| **Bullish TA vs neutral IC** | Technical 73.4 bullish, Iron Condor neutral | **Intentional** — IV-rich + range-bound RSI selects premium-selling neutral structures | Not a bug; `selection_rationale` copy added |

## Universal validator checks (every trade card)

| # | Check | Validator key | Applies to |
|---|-------|---------------|------------|
| 1 | Credit recomputation from leg mids | `credit_recomputation`, `max_profit_credit_match`, `max_loss_credit_match`, `breakeven_credit_match` | All multi-leg credit/debit structures with `payoff_function_ref` |
| 2 | Moneyness monotonicity | `moneyness_monotonicity` | Spreads, condors, butterflies, iron butterflies (see `_MONOTONIC_PAYOFF_REFS`) |
| 3 | Anchor leg == order ticket | `anchor_strike_match`, `anchor_expiry_match`, `anchor_side_match`, `order_*_match` | All strategies with `recommended_contract` / order legs |
| 4 | `equity_required` boundary | `equity_leg_required`, `equity_forbidden`, `equity_overlay_options` | Equity-overlay vs options-only registry specs |
| 5 | Score bounds [0, 100] | `score_bounds` | `scan_scores` on every card; hard-fail at computation for IV rank and composite inputs |

Wired in `build_strategy_layer` and `scan_engine` before trade card emission. Blocks card (`tradeable: false`) on any failure.

## IV Rank consolidation

Single pipeline in `app/analysis/volatility.py`:

| Function | Role |
|----------|------|
| `range_rank` / `percentile_rank` | Internal; `assert_score_in_bounds` at return |
| `iv_rank_from_history` | True rank from IV history |
| `iv_rank_proxy(atm_iv, hv)` | Documented proxy when no history |
| `compute_iv_rank(...)` | **Single entry point** — history first, proxy fallback, always [0, 100] or `None` |

**Call sites unified:**

| Location | After |
|----------|-------|
| `volatility_intel.build_volatility_payload` | `compute_iv_rank` |
| `scan_engine.build_layers` | sanitize `vol_layer`; proxy fallback via `compute_iv_rank` / `iv_rank_proxy` |
| `options_analysis.build_chain_analysis` | `iv_rank_proxy` from volatility module (no local duplicate) |

## Score bounds at source

| Score | Source module | Enforcement |
|-------|---------------|-------------|
| IV Rank / percentile | `volatility.py` | `assert_score_in_bounds` on every return path |
| Composite + pillars | `composite_score.py` | `assert_score_in_bounds` on inputs and final composite |
| Technical | `ta/pipeline.py` → `composite_technical_score` | `assert_score_in_bounds("technical_score", …)` |
| Sentiment | `sentiment_layer.py` | `assert_score_in_bounds("sentiment_score", score_0_100)` |
| Scan assembly | `scan_engine.py` | `validate_scan_scores(...)` before strategy layer |

## Payoff / leg consistency

- `make_option_leg` rounds mids to 2 decimals at creation
- `_finalize` normalizes legs and recomputes net from displayed mids before setting summary fields
- Credit structures pass single `net_credit` derived from normalized legs into payoff handlers

## Test coverage

| File | Scope |
|------|-------|
| `test_platform_trade_card_invariants.py` | **Primary** — parametrized 98 strategy IDs × 5 tickers; 6 bug-injection pairs; MSFT iron condor regression |
| `test_all_100_strategies.py` | All 100 registry entries build + validate |
| `test_iron_condor_msft_regression.py` | MSFT IC bug classes + IV rank bounds |
| `test_strategy_registry_validation.py` | Calendar, APEX, equity edge cases |
| `test_equity_policy_and_bounds.py` | Anchor leg, equity policy, IV rank cap |

Run: `cd backend && python3 -m pytest` and `cd frontend && npm test`.

## Residual risks

- Live vendor quotes can still be stale; validator now **blocks** the trade card instead of showing inconsistent economics
- IV Rank proxy (no history) is explicitly labeled and bounded — not a true 52-week rank
- Calendar / APEX paths retain separate IV-dependent payoff assumptions (unchanged)
- 11 registry strategies are implemented but marked `tradeable=False` (undefined risk); validator still runs when metrics are built for review
