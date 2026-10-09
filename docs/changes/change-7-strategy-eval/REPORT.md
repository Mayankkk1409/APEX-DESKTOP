# Change 7 — Registry evaluation and one Best Match

## Evaluation count

Each call to `recommend_strategy` walks every entry in `STRATEGY_REGISTRY` (100). The integer `strategies_evaluated` is that count, equal to the registry size. It is returned on `StrategyRecommendation` and stored on the strategy layer of the scan payload.

Eligible defined-risk names still come from the existing §9.1 matrix and are reordered by the saved risk profile. The first eligible defined-risk name is the only Best Match. A score under the auto-execution minimum does not remove that name or its legs.

## Misses are kept

- A registry name that fails the matrix is still returned, with `eligible: false` and one short `gate_notes` phrase already used by the matrix (for example `IV cheap`, `Range-bound RSI`, `Catalyst window active`, or `No defined-risk strategy matched the current regime.`)
- A matrix match removed by the risk-profile allowlist keeps the gate notes it already had, and is not the Best Match
- Names in the undefined-risk exclusion set are not added as candidates. Their reason is appended to `rejection_reasons` as `<name>: excluded from automated execution`

## Test

`backend/tests/test_structure_payoff.py::test_scan_evaluates_registry_and_selects_one_label`

A bullish scan with both cheap IV versus HV and a sell-premium signal evaluates 100 strategies, has more than one eligible structure, and returns exactly one selected label.

`test_chain_bull_call_max_loss_is_net_debit_times_multiplier` checks that a debit vertical's max loss equals net debit times the contract multiplier (within $0.01).

## Files

- `backend/app/services/strategy_recommendation.py` — registry walk, `strategies_evaluated`, miss notes
- `backend/app/services/strategy_engine.py` — outlook, why it fits, count on the strategy layer
- `backend/app/services/scan_engine.py` — count passed through on the scan; fit text keeps the real composite
- `backend/app/strategies/structure_math.py` — Decimal closed forms
- `backend/app/strategies/metrics_builder.py` — applies those forms and Unlimited on undefined risk
- `frontend/src/components/StrategyScan.tsx` — name, outlook, why it fits, legs, payoff, Unlimited, evaluation count
- `frontend/src/types.ts` — layer fields
- `backend/tests/test_structure_payoff.py`
- `frontend/src/components/scanSlides.test.tsx`
