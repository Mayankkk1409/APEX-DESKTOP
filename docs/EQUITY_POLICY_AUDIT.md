# APEX Equity Policy Audit

**Date:** 2026-08-31  
**Scope:** Strategy registry, leg builder, validator, scan execution, trade card display.

## Executive summary

APEX is an **options-first** platform. Equity orders are permitted **only** when `strategy.equity_required == true` and the payload matches the registry composition. The production **Married Call / NVDA** defect was traced to a misnamed single-leg long call that ignored the scan anchor contract when building order legs.

## Root cause — Married Call (NVDA)

| Defect | Root cause | Fix |
|--------|------------|-----|
| Anchor 215 vs order 220 | `metrics_builder._build_single_long` used `pick_strike(Δ≈0.55)` instead of `recommendedContract` | `resolve_contract_from_recommended()` — single source of truth |
| IV Rank 128.9 | `range_rank()` allowed values above historical max (>100) | Cap at 100 when `value >= hi`; hard `assert_score_bounded` on all 0–100 fields |
| Incomplete order (call only) | Registry entry `married_call` was a lone long call mislabeled as stock+call | Renamed legacy alias → **APEX Benchmark Greeks Strategy**; encyclopedia entry → **Leveraged Covered Call** (stock+call) |
| Max loss $873 (call-only) | Payoff used `payoff_long_option` on premium only | Benchmark Greeks uses correct long-call math; Leveraged Covered Call uses combined stock+call payoff |
| Wrong taxonomy | “Married” applies to puts hedging stock (Married Put / Protective Put) | Removed “Married Call” from selection; display alias maps to Benchmark Greeks |

## Naming decision

- **Playbook selection:** `Married Call` → **`APEX Benchmark Greeks Strategy`** (options-only, Δ ≥ 0.55 long call).
- **Encyclopedia Family 7:** Replaced `married_call` with **`Leveraged Covered Call`** (`stock + long call`, `equity_required=true`).
- **Synthetic structures:** Remain options-only (no equity execution).

## Registry — `equity_required` tagging

| Category | Strategies |
|----------|------------|
| **Simultaneous equity + options** | Covered Call, Covered Put, Collar, Protective Collar, Leveraged Covered Call, Conversion, Reversal |
| **Pre-existing shares overlay** | Married Put, Stock + Short Call, Stock + Long Put |
| **Options-only (never equity)** | All spreads, straddles, calendars, condors, butterflies, PMCC, synthetics, APEX Strategy, Benchmark Greeks, Long/Short single legs |

## Mismarked / corrected strategies

| Before | Issue | After |
|--------|-------|-------|
| `married_call` | Misnamed long call; implied stock | `leveraged_covered_call` with stock leg + combined payoff |
| `married_put` | Missing equity tag | `equity_required=true`, `pre_existing` overlay |
| `stock_short_call` / `stock_long_put` | Untagged | `equity_required=true`, `pre_existing` |
| Playbook “Married Call” | Selected for sentiment bull cases | **APEX Benchmark Greeks Strategy** |

## Execution pipeline gates

- **`validator.py`:** Equity composition, anchor leg == order ticket, score bounds [0,100].
- **`scan_engine.py`:** Builds `strategy_legs` (options) and `equity_legs` (simultaneous only); blocks trade card if simultaneous equity strategy lacks stock leg.
- **`fills.py` / `portfolio.py`:** Rejects stock legs for options-only strategies; requires equity legs for simultaneous equity strategies.

## Anchor / order invariant

Universal rule: **primary option leg strike, expiry, and side == `recommended_contract` == order ticket.**

Validator checks: `anchor_strike_match`, `anchor_expiry_match`, `order_occ_match`.

## Out-of-bound scores

All surfaced 0–100 metrics (`iv_rank`, `iv_percentile`, composite, technical, sentiment, fundamentals, `hv_rank`) pass through `assert_score_bounded()` — values outside [0,100] **throw** and block the trade card.

## Payoff corrections

| Strategy | Prior max loss | Correct max loss |
|----------|----------------|------------------|
| Mislabeled Married Call | Call premium × 100 | Benchmark Greeks: call premium × 100 (correct for long call) |
| Leveraged Covered Call | N/A (was call-only) | (stock cost + call premium) × 100 |

## Frontend

- **StrategyScan:** Anchor leg read from `metrics.legs` (same payload as order), not a divergent recommended contract.
- **Banner:** `equity_required` strategies show stock purchase/overlay messaging.

## Residual items

- **Wheel Strategy:** Options-first phase (short put); equity acquisition is lifecycle-stage — remains options-only at entry.
- **Pre-existing overlay strategies:** Options leg submitted; user must hold shares (banner + future portfolio gate).
