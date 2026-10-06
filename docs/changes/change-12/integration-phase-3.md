# Change 12 — Phase 3 integration

Branch: `change12/base`. No new branch. No force-push. No branch was deleted.

Command after every suite, from `backend/`, outside the sandbox:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

`change12/3C` was already on this branch (`359057d`). The suite recorded for that merge is **1717 passed, 59 skipped, 0 failed**.

## Merge order

| Order | Branch | Tip | Merge commit | Backend suite |
| --- | --- | --- | --- | --- |
| already on base | `change12/3C` | `cd698c9` | `359057d` | 1717 passed, 59 skipped, 0 failed |
| already on base | `change12/3B` | `f188973` | `ff10a2862bc4e6bc7809a75be2aacec60e8de84a` | first re-run: 1 failed, 1721 passed, 59 skipped. After the short-delta ledger fix below: **1722 passed, 59 skipped, 0 failed** |
| 1 | `change12/3A` | `0cc170358ea9f4632c534ebaf8e24f9c92866416` | `0e688db12171241a2d18e0e8fb749b0c2cd22153` | **1727 passed, 59 skipped, 0 failed** |
| 2 | `change12/3D` | `d4a01d1e224abbba0d4904513ca2e871f234495e` | `f40d772ff0d1082c6990526014f43cedc53cc90e` | **1735 passed, 59 skipped, 0 failed** |

Both merges used `--no-ff`. Neither conflicted. After the integration edits below, the same command was **1735 passed, 59 skipped, 0 failed**.

The 3B re-run failed `tests/test_strategy_engine.py::test_aapl_bull_put_legs_keep_structure_name_and_payoff`. The Bull Put how-to cites a short delta of 0.20. That figure was not on the ledger, so `check_narrative` replaced the card with ledger fact lines, including the name `IV Crush Short Iron Condor`. `strategy_engine.py:3896` now records `rule2_short_delta_max()` when the how-to prints that cap. The test was not weakened.

## Requests applied

1. `options_analysis.py:421` sets the vol signal with `assess_vol_regime` when ATM IV and HV are both present. A 9.93 vol-point gap (IV 30.31% versus HV 20.38%) is rich, the same primary result as the card. The vega-cap check at `options_analysis.py:474` still uses `iv_hv_rich_pts` (10 vol points). That threshold was not changed.
2. These card sentences now go through `check_narrative`. A rejected token is logged and replaced with the ledger-filled template.
   - `equity_note` (`strategy_engine.py:3922`)
   - `selection_rationale` (`strategy_engine.py:3928`)
   - `hard_block_reasons` (`strategy_engine.py:3934`)
   - `spread_block_reasons` (`strategy_engine.py:3939`)
   - `block_reason` (`strategy_engine.py:3945`)
   - the composite sentence `_restore_scored_strategy_layer` writes onto `why_it_fits` (`scan_engine.py:1067`)
   - the risk note added when the equity leg is missing (`scan_engine.py:628`)
   Share counts and cost basis that the holdings note already prints are stored on the metrics before the check (`stock_leg.py` equity share and cost-basis fields). No market number was invented.
3. `scan_engine.py:869` calls `_show_measured_event_vega` (`scan_engine.py:874`). When the ledger already stores a numeric `event_vega_penalty` for the scan, that row is appended to the risk section of the APEX score slide. A missing premium is not shown. Weights were not changed.

Composite weights stay technicals 30%, volatility 25%, options 20%, sentiment 15%, fundamentals 10%, risk 0%. The 300-second quote cap, the spread cap, and the ±5 vol-point band were not loosened.
