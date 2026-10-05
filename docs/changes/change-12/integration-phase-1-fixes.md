# Change 12 — Phase 1 fixes closed in Phase 3

Recorded 5 October 2026 on `change12/base`. These items were still open after Phase 2 integration (`1651 passed, 59 skipped, 0 failed`).

## Quote with a price and no timestamp

`quote_is_stale` in `backend/app/analysis/gate_config.py` still treats a missing timestamp as not an age failure. That helper is not the order path.

`quote_problem` in `backend/app/services/executability.py` is what `enforce_submission_quotes` calls before a fill. A quote that has a price, bid, or ask and no parseable `as_of` now returns `Quote not current. Quoted unknown time.` A missing timestamp is not treated as fresh on submission. The 300-second cap is unchanged. Outside regular hours, a last-close quote that has a real timestamp is still not a failure by market hours alone.

`execute_market_fill` in `backend/app/services/fills.py` no longer accepts `skip_quote_check`. The quote check always runs. Tests do not pass a bypass flag. Fixtures that submit orders now carry a timestamp.

## `contracts.canAutoExecute`

`canAutoExecute` in `backend/app/contracts.py` calls `app.services.executability.can_auto_execute` and returns `AutoExecuteDecision(eligible, reasons)`. It does not raise. `contracts.ledger.record` still drops the entry. Card values are stored with `app.services.evidence_ledger.record` / `record_card_value`.

## Frontend suite

Command: `npm test` (`vitest run`) from `frontend/`, 5 October 2026.

**301 passed, 1 failed** (55 files: 54 passed, 1 failed).

The failure is `src/pages/DeepScan.order.test.tsx` › `shows Place Trade below the saved minimum`. The rendered note is `Manual confirmation required (score 39.0 vs. your auto-execute minimum 40.0).` The test expects `score 39` and `minimum 40` without the decimal. This file was not edited in this change. The assertion was not weakened.

## Backend skips (59), same count as the Phase 1 baseline

Command: `pytest -q --tb=line -rs` from `backend/` with the project virtualenv. Result after these fixes: **1659 passed, 59 skipped, 0 failed**. The eight extra passes are the Phase 3 narrative, regime, event-vega, and order-path tests in `backend/tests/test_change12_phase3.py`. No skip was removed and no threshold was loosened to keep the count at 59.

Each skip is the test refusing to invent a chain. The reason string is the one pytest printed.

### `tests/test_all_100_strategies.py:109` — builder blocked without optional chain data (7)

The mock front chain does not include the extra series these structures need. `build_registry_metrics` sets `validation_blocked`, and the test skips rather than asserting a made-up card.

1. `covered_put`
2. `dispersion_trade`
3. `long_call_leaps`
4. `long_put_leaps`
5. `long_straddle_leaps`
6. `reversal`
7. `synthetic_put`

### `tests/test_iron_condor_msft_regression.py:222` — leg count mismatch on mock chain (15)

`test_valid_mock_chain_passes_moneyness_and_credit` builds one monotonic mock chain (strikes 85–115, spot 100) for AAPL, MSFT, and TSLA. These five ids still come back with a leg count other than the template. The test skips each ticker instead of changing `leg_count` or the chain.

8. `bear_put_spread` / AAPL
9. `bear_put_spread` / MSFT
10. `bear_put_spread` / TSLA
11. `bull_put_spread_credit` / AAPL
12. `bull_put_spread_credit` / MSFT
13. `bull_put_spread_credit` / TSLA
14. `put_debit_spread` / AAPL
15. `put_debit_spread` / MSFT
16. `put_debit_spread` / TSLA
17. `put_credit_spread` / AAPL
18. `put_credit_spread` / MSFT
19. `put_credit_spread` / TSLA
20. `wide_bear_put_spread` / AAPL
21. `wide_bear_put_spread` / MSFT
22. `wide_bear_put_spread` / TSLA

### `tests/test_platform_trade_card_invariants.py:282` — builder blocked without optional chain data (37)

`TEST_MATRIX` spots are AAPL 100, MSFT 500, TSLA 250, NVDA 218, SPY 550. The same optional-data block as the catalog test. `apex_strategy` builds on AAPL, TSLA, and NVDA in this matrix, so those three are not in the skip list.

23. `covered_put` / AAPL
24. `dispersion_trade` / AAPL
25. `long_call_leaps` / AAPL
26. `long_put_leaps` / AAPL
27. `long_straddle_leaps` / AAPL
28. `reversal` / AAPL
29. `synthetic_put` / AAPL
30. `apex_strategy` / MSFT
31. `covered_put` / MSFT
32. `dispersion_trade` / MSFT
33. `long_call_leaps` / MSFT
34. `long_put_leaps` / MSFT
35. `long_straddle_leaps` / MSFT
36. `reversal` / MSFT
37. `synthetic_put` / MSFT
38. `covered_put` / TSLA
39. `dispersion_trade` / TSLA
40. `long_call_leaps` / TSLA
41. `long_put_leaps` / TSLA
42. `long_straddle_leaps` / TSLA
43. `reversal` / TSLA
44. `synthetic_put` / TSLA
45. `covered_put` / NVDA
46. `dispersion_trade` / NVDA
47. `long_call_leaps` / NVDA
48. `long_put_leaps` / NVDA
49. `long_straddle_leaps` / NVDA
50. `reversal` / NVDA
51. `synthetic_put` / NVDA
52. `apex_strategy` / SPY
53. `covered_put` / SPY
54. `dispersion_trade` / SPY
55. `long_call_leaps` / SPY
56. `long_put_leaps` / SPY
57. `long_straddle_leaps` / SPY
58. `reversal` / SPY
59. `synthetic_put` / SPY

## Alpaca plan, feed, and delay

Read from this app's settings on 5 October 2026. Only the mode and whether keys are present were printed. Key values were not printed.

| Setting | Value in this checkout |
|---|---|
| `alpaca_trading_mode` | `paper` (config default, and the loaded settings) |
| API keys | present |
| Options feed | `indicative` |

`AlpacaAdapter.__init__` sets `feed` to `opra` only when `alpaca_trading_mode == "live"`. Paper uses `indicative` (`backend/app/adapters/alpaca.py`). The health payload uses the same rule (`backend/app/routers/health.py`).

This is Alpaca's Trading API Basic plan, which is the default for paper and live and costs nothing. Basic options coverage is the indicative feed. Algo Trader Plus is $99 per month and is the plan that includes the OPRA feed. It was not purchased. Whether to buy it is a team decision.

Sources, fetched 5 October 2026:

- About Market Data API, Trading API subscriptions: Basic is free and includes the indicative options feed; Algo Trader Plus is $99/month and includes OPRA. Options historical data on Basic is limited to the latest 15 minutes. https://docs.alpaca.markets/us/docs/about-market-data-api
- Historical option data: the indicative feed is a free derivative of OPRA. Quotes are not actual OPRA quotes. Trades are delayed 15 minutes. OPRA is the consolidated best bid and offer and is only for subscribed users. https://docs.alpaca.markets/us/docs/historical-option-data
- Real-time option data: the websocket path is `wss://stream.data.alpaca.markets/v1beta1/{feed}` with `indicative` or `opra`. https://docs.alpaca.markets/us/docs/real-time-option-data
- Latest quotes: `feed=opra` is the official OPRA feed; `feed=indicative` is the free feed where trades are delayed and quotes are modified. Default is `opra` if subscribed, otherwise `indicative`. https://docs.alpaca.markets/us/reference/optionlatestquotes
- Pricing page lists Algo Trader Plus at $99/mo. https://alpaca.markets/data
