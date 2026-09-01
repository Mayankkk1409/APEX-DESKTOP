# Strategy Validation Audit

Last updated: 2026-08-31 (full 100-strategy implementation pass).

## Summary

| Metric | Count |
|--------|------:|
| Registry strategies | 100 |
| Implemented payoff refs | **98** |
| Advisory (no legs / no payoff) | 2 |
| Pass validator with mock chain | **98/98** tradeable |
| Fail validator | **0** |

The two advisory entries (`NO TRADE — Insufficient Conviction`, `NO TRADE — Wait for IV Crush`) have `leg_count=0`, `tradeable=false`, and skip payoff validation by design.

## Architecture

| Module | Role |
|--------|------|
| `strategies/registry.py` | 100 canonical specs with `payoff_function_ref` on all tradeable entries |
| `strategies/payoffs/core.py` | 35 payoff handlers + shared helpers |
| `strategies/payoffs/helpers.py` | Scan, breakeven root-finding, multi-leg P/L |
| `strategies/chain_utils.py` | Strike picking, OCC leg assembly, stock legs |
| `strategies/metrics_builder.py` | Per-`strategy_id` leg builders + payoff dispatch |
| `strategies/validator.py` | Leg count, OCC/stock consistency, payoff shape gates |
| `services/strategy_engine.py` | Delegates to `metrics_builder` before legacy name handlers |

## Payoff handler catalog

| Handler | Strategies |
|---------|------------|
| `payoff_long_option` | Long call/put, LEAPS, deep ITM, ATM, benchmark Greeks, VIX hedge, wheel, married put/call |
| `payoff_short_option` | Naked call/put |
| `payoff_vertical_debit` | Bull/bear debit spreads, wide spreads, PMCC-style verticals, vega neutral |
| `payoff_vertical_credit` | Bull/bear credit spreads |
| `payoff_long_straddle` | Long straddle variants, earnings, gamma scalping, synthetic straddle |
| `payoff_long_strangle` | Long strangle |
| `payoff_short_straddle` | Short straddle, short guts |
| `payoff_short_strangle` | Short strangle |
| `payoff_long_guts` | Long guts |
| `payoff_strip` / `payoff_strap` | Strip / strap (ratio quantities on legs) |
| `payoff_calendar_spread` | Calendar, reverse calendar, diagonals |
| `payoff_double_calendar` | Double calendar, calendar straddle, double diagonal, jelly roll |
| `payoff_butterfly` / `payoff_short_butterfly` | Long/short call & put butterflies |
| `payoff_iron_butterfly` / `payoff_long_iron_butterfly` | Iron butterfly variants |
| `payoff_iron_condor` / `payoff_long_iron_condor` | Iron condor family |
| `payoff_condor_spread` | Call/put condor, box spread legs |
| `payoff_broken_wing_butterfly` | Broken wing, skip strike |
| `payoff_christmas_tree` | Christmas tree |
| `payoff_multi_leg_scan` | Ratio spreads (undefined risk) |
| `payoff_backspread` | Call/put backspreads |
| `payoff_jade_lizard` | Jade / reverse jade lizard |
| `payoff_covered_call` | Covered call, stock + short call |
| `payoff_covered_put` | Covered put |
| `payoff_protective_put` | Stock + long put |
| `payoff_collar` | Collar, protective collar |
| `payoff_synthetic_long` / `payoff_synthetic_short` | Synthetic stock, combos |
| `payoff_conversion` | Conversion, reversal |
| `payoff_box_spread` | Box spread |
| `payoff_risk_reversal` | Risk reversal, vol skew |
| `payoff_pmcc` | Poor Man's Covered Call |
| `payoff_dispersion` | Dispersion trade (correlation-dependent; index leg not modeled) |
| `payoff_apex_strategy` | APEX Strategy 4-leg catalyst |

## Undefined-risk strategies

Implemented with payoff + leg builders; `tradeable=false` in registry; excluded from auto-exec:

- Naked call / naked put
- Short straddle / short strangle / short guts
- Ratio spreads (all variants)
- Jade lizard / reverse jade lizard
- Covered put (naked stock risk)

## Stock-position notes

These require stock legs in the built payload (100 shares at spot). Payoffs model entry at current spot:

- Covered call, stock + short call
- Covered put (undefined risk)
- Collar, protective collar
- Stock + long put
- Conversion, reversal

**Dispersion trade** — registry models single-name call sell/buy pair; full index-vs-single dispersion requires a second underlying not present in the options chain snapshot. Payoff is flagged `iv_assumption_dependent` with advisory notes.

**Married put / married call** — registry uses option leg only (stock assumed held); full combo certificate shows protective option leg.

## Test coverage

- `backend/tests/test_all_100_strategies.py` — parametrized: all 100 registry IDs
- `backend/tests/test_strategy_registry_validation.py` — calendar/APEX safeguards + double calendar
- Full backend suite: **375 passed**

## Safeguards (unchanged)

- Validator blocks wrong leg counts (calendar/APEX regression tests)
- `build_strategy_layer` sets `tradeable=false` on validation errors
- Undefined-risk never in auto-exec candidate list
