# Change 12 — agent 3C

Branch: `change12/3C`. Worktree: `/Users/Mayank/Desktop/APEX-change12-3C`. Base: `change12/base` plus the phase 3 WIP commit `8e58381`.

Item (d) was already marked done. The order-path code was verified and left in place. The frontend assertion was the failure.

## Root causes

| What | Where |
| --- | --- |
| Place Trade note test expected integers | `frontend/src/pages/DeepScan.order.test.tsx:139` expected `score 39` and `minimum 40` |
| Screen already prints one decimal | `frontend/src/lib/riskReview.ts:34` calls `formatCompositeDecimal`; `frontend/src/lib/scoreFormat.ts:7` uses `toFixed(1)` |
| A priced quote with no timestamp is blocked on submission | `backend/app/services/executability.py:156-158` returns `Quote not current. Quoted unknown time.` |
| That check runs before every fill, including a demo fill | `backend/app/services/fills.py:182` calls `enforce_submission_quotes` before `_submit_for_fill`; `force_paper` only changes the broker at `fills.py:115` |
| Demo quotes already carry a clock | `backend/app/adapters/demo.py:196` sets `as_of` |
| Contract delegates and does not raise | `backend/app/contracts.py:77-82` |
| Age-only helper still ignores a missing clock | `backend/app/analysis/gate_config.py:594-595`. The order path does not use that as a pass. `QUOTE_FRESHNESS_SECONDS` is `300` at `gate_config.py:16`. Age equal to 300 is inside the cap; 301 is not (`quote_is_stale` returns `age > 300` at `gate_config.py:610`) |

`skip_quote_check` is not a parameter of `execute_market_fill`, `execute_strategy_legs`, or `enforce_submission_quotes`, and it does not appear in `fills.py`, `executability.py`, `expiry_close.py`, `portfolio.py`, `demo.py`, or `contracts.py`. No test passes it.

## Changes

- `frontend/src/pages/DeepScan.order.test.tsx` — the below-minimum assertion now expects `39.0` and `40.0`.
- `backend/tests/test_change12_3c.py` — order-path checks. Production order code was not rewritten.
- This file and the frontend count appended to `integration-phase-1-fixes.md`.

`executability.py`, `fills.py`, `contracts.py`, and `demo.py` were not edited. `LedgerEntry`, `QuoteMeta`, `EarningsInfo`, and `VolRegime` field names were not changed. The formatter was not changed.

## Tests

`backend/tests/test_change12_3c.py`:

| Test | What it checks |
| --- | --- |
| `test_priced_quote_without_a_timestamp_is_unknown_time` | Price, bid, or ask with `None`, `""`, or an unparseable clock is `Quoted unknown time`. `quote_is_stale` still returns false for a missing clock. The cap stays 300. |
| `test_three_hundred_second_cap_is_unchanged` | 300 seconds during the session is current. 301 seconds is `Quote not current`. |
| `test_demo_quote_carries_a_timestamp` | `DemoAdapter.quote` for AAPL and an OCC symbol sets `as_of`, and `quote_problem` is clear. |
| `test_demo_fill_blocks_a_price_with_no_timestamp` | `execute_market_fill(..., force_paper=True)` and `execute_strategy_legs` raise `Quoted unknown time`. `DemoAdapter.submit_order` is not called. The quote is read twice (one refetch). |
| `test_expiry_close_path_uses_the_same_quote_check` | The expiry-close path, with `force_paper` and `closing`, blocks the same way. |
| `test_can_auto_execute_delegates_and_does_not_raise` | `contracts.canAutoExecute` calls `executability.can_auto_execute` and returns `eligible` plus `reasons`. `None`, empty, a string, and a bare object do not raise. |
| `test_skip_quote_check_is_absent_from_order_paths` | The name is not a parameter and no test assigns it. |

## Results

Frontend, `npm test` from `frontend/` on 5 October 2026:

**302 passed, 0 failed** (55 files passed). Duration 74.64s.

Backend, outside the sandbox, cwd `backend/`:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line -rs`

**1717 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). 1293.68s.

The 59 skips match the Phase 1 baseline in `integration-phase-1-fixes.md`. Same three files, same reasons, same names. No skip was removed.

- `tests/test_all_100_strategies.py:109` — 7, builder blocked without optional chain data
- `tests/test_iron_condor_msft_regression.py:222` — 15, leg count mismatch on the mock chain (five structures × AAPL, MSFT, TSLA)
- `tests/test_platform_trade_card_invariants.py:282` — 37, builder blocked without optional chain data

The recorded 1659 was the suite before the phase 3 WIP commit on this branch. This run includes that commit's tests and these seven checks.

## Alpaca plan, feed, and delay

This checkout's code uses the Trading API. `alpaca_trading_mode` defaults to `paper` (`backend/app/config.py:46`). `AlpacaAdapter.__init__` sets `feed` to `opra` only when the mode is `live`; otherwise `indicative` (`backend/app/adapters/alpaca.py:198`). Health uses the same rule (`backend/app/routers/health.py:14`).

Loaded settings in this worktree: mode `paper`, keys absent (no `.env` in the worktree; key values were not printed), adapter feed `indicative`. Paper mode stays on the indicative feed even when keys are present. Algo Trader Plus was not purchased.

That is Alpaca's Trading API Basic plan: free, and the default for paper and live. Options coverage on Basic is the indicative feed. Indicative quotes are not OPRA quotes. Indicative trades are delayed 15 minutes. Algo Trader Plus is the real-time OPRA upgrade and is still listed at **$99/month**. Buying it is a team decision.

## Sources

Fetched 5 October 2026. Nothing was purchased.

- [About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api). Trading API Basic is free and is the default for paper and live. Equities on Basic are IEX. Options on Basic are the indicative feed. Historical options on Basic omit the latest 15 minutes. Algo Trader Plus is $99/month and includes OPRA, with no 15-minute historical restriction.
- [Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data). The indicative feed is a free derivative of OPRA. Quotes are not actual OPRA quotes. Trades are delayed 15 minutes. OPRA is the consolidated best bid and offer and is only for subscribed users.
- [Alpaca data pricing](https://alpaca.markets/data). Algo Trader Plus is listed at $99/mo.

## Open questions

- This worktree has no `.env`, so a process started here reports keys absent and the demo market adapter. The feed selection for paper is still `indicative`. The base checkout's earlier note that keys were present was not re-checked by printing secrets.
- Whether to buy Algo Trader Plus ($99/month) for OPRA is still a team decision. The 300-second age cap and the 10% spread cap were not changed.

## Requests for other owners

None. The order path, the contract, and the demo quote clock already match the phase 3 note. `strategy_engine.py`, `narrative_guard.py`, `volatility_intel.py`, the QA replay, and `REPORT.md` were not edited.
