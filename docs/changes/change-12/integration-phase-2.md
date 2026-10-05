# Change 12 — Phase 2 integration

Branch: `change12/base`. Phase 3 has not started. Frozen `LedgerEntry` field names were not changed. `contracts.ledger.record` still drops its entry. `canAutoExecute` in `contracts.py` still raises. The live decision stays `app.services.executability.can_auto_execute`. The live store is `app.services.evidence_ledger`.

Command after every merge, from `backend/`:

`backend/.venv/bin/python -m pytest -q --tb=line`

The sandbox hides pytest-asyncio, so the suite was run outside the sandbox. A sandboxed run reports setup errors that are not product failures.

## Merge order

No conflicts. Each branch was merged with `--no-ff` from `change12/base` at `51dbcf9`.

| Order | Branch | Merge commit | Backend suite |
| --- | --- | --- | --- |
| 1 | `change12/2B` (`7a69bcc`) | `5a4a12d` | 1544 passed, 59 skipped, 0 failed |
| 2 | `change12/2C` (`5de9c25`) | `40b02a1` | 1633 passed, 59 skipped, 0 failed |
| 3 | `change12/2A` (`f5a1d5b`) | `b0c312a` | 1650 passed, 59 skipped, 0 failed |

After the integration edits below: **1651 passed, 59 skipped, 0 failed**.

## Requests applied

1. `record_ledger` in `strategy_recommendation.py` writes through `evidence_ledger.record`. Regime, gates, candidates, scores, and rank from a strategy decision are stored under the symbol as the scan id. Tests read `evidence_ledger.get` instead of the dropping stub.
2. Option DTE comes from the catalog. `dte_min` 366 with no `dte_max` means more than 365 calendar days. Both bounds empty does not borrow a window from how-to text. The Gamma Trampoline™ 5–10 day band stays the earnings window. `dte_window_for("Gamma Trampoline™")` is `None`. `dte_window_for("Long Call LEAPS")` is `(366, None)`.
3. The volatility slide no longer prints a bare dash for a missing IV rank or IV percentile. The value is `unavailable:` plus the history reason, or `published IV history is missing` when no shorter reason exists.

Score weights were not changed. The 300-second quote cap and the 10% spread cap were not changed.

## Carried forward

- `volatility_intel._iv_hv_signal` still treats a gap above 10 points as rich or cheap, a gap within 5 points as fair, and the band between as `between_bands`. The strategy card uses the ±5 rule from `assess_vol_regime`. One label everywhere is still open. The 10-point function was left in place so existing `vol_signal` callers do not flip during this merge.
- The event-vega sentence names the long leg, the date, and the IV premium in points. It is written after the legs exist, so it does not change which name ranks first.
- `check_narrative` is implemented and tested. The strategy layer does not pass card text through it yet. Wiring it before every card number is on the ledger would reject current explanations.
- Stated-premium golden scenarios are expiry-identity checks, not feed quotes. They are not written into the scan ledger as market quotes.
- 17 two-expiry and dispersion strategies still have no recorded chain. That is stated in `agent-2C.md`.
