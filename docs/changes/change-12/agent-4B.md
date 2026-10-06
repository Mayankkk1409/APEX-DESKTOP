# Change 12 — agent 4B

Branch: `change12/4B`. Worktree: `/Users/Mayank/Desktop/APEX-change12-4B`. Base: `297104c`.

## The reported stack

A defined-risk spread returned five sentences:

> Account not eligible to trade uncovered option contracts. The combo was not split into market orders. No short leg was submitted. The short call was not submitted. Remaining short legs were not submitted.

Three faults in one message:

1. **Two writers.** `_execute_combo` already ends its rejection with `The combo was not split into market orders. No short leg was submitted.` That `ValueError` was raised inside the `try` block of `execute_strategy_legs`, so the generic `except Exception` handler ran `_holdback(exc, short_leg=False)` and appended `The short call was not submitted. Remaining short legs were not submitted.` on top (`fills.py:429-439` and `fills.py:501-504` before this change).
2. **An invented naked short.** The combo is one `mleg` limit. No leg is ever submitted on its own, so both appended sentences described an order that never existed.
3. **No paper fill.** A paper account only fell back to the local book for a closed session (`_SESSION_PAPER_MARKERS`). An uncovered-option refusal is an approval-level property of the broker account, not a property of the structure, so the paper path raised instead of filling. That is the regression the user felt.

The broker sentence itself is not built in this repo. `alpaca_order_error_message` (`backend/app/adapters/alpaca.py:78`) returns the broker's own `message` field, and `_submit_combo` passes it through as `{"status": "rejected", "rejected": True, "reason": …}` (`alpaca.py:725-731`). `alpaca.py` was not edited. `demo.py` was not edited either: the demo fill does not bypass validation, because `enforce_submission_quotes` runs before any submission on both order paths.

## Changes — `backend/app/services/fills.py` only

| What | Where |
| --- | --- |
| `ComboHeldBack(ValueError)` — a rejection whose sentence already covers the holdback | `fills.py:63` |
| `_UNCOVERED_PAPER_MARKERS` — `uncovered option`, `naked option`, `not eligible to trade uncovered`, `not approved for uncovered` | `fills.py:52-60` |
| `_paper_fillable(reason)` — closed session **or** uncovered refusal | `fills.py:92` |
| `paper_fill_sentence(reason)` — the broker reason, then `The paper order filled at the mid.` | `fills.py:79` |
| Every combo rejection raises `ComboHeldBack`: broker refusal, `TypeError` on a non-combo adapter, insufficient buying power, an unpriceable net mid | `fills.py:717-798` |
| Paper account + `_paper_fillable` → fill the whole combo at the net mid | `fills.py:781-798` |
| The local combo fill re-runs `enforce_submission_quotes` on every leg before it fills | `fills.py:786-797` |
| `execute_strategy_legs` re-raises `ComboHeldBack` untouched, and never applies `_holdback` when `len(legs) >= 2` | `fills.py:553-560` |
| `_holdback` returns the reason unchanged when it already says `No short leg was submitted` | `fills.py:476-481` |
| The note rides on `order.fill_note` and on the `fill` websocket frame as `note` | `fills.py:333`, `fills.py:348`, `fills.py:693`, `fills.py:820` |

### What a paper account now sees

One notice, broker reason first:

> Account not eligible to trade uncovered option contracts. The paper order filled at the mid.

The combo fills at the net mid of the chain — `abs(combo_net_mid(legs, marks))`, the same limit that was sent to the broker — and both legs open together, so the structure stays defined-risk. Nothing about a short call or remaining short legs is appended, because nothing naked was sent.

### What still refuses

- **Real brokerage.** `session_paper = user.account_mode != "real_brokerage"` gates every paper fallback. A `real_brokerage` account keeps the broker's rejection plus the two-sentence holdback and opens no position.
- **Any other broker reason.** `Broker rejected the order`, a buying-power refusal, or an unknown contract is not in either marker list, so it still raises. The existing tests that assert this (`test_stock_leg.py:291`, `test_apex_four_legs.py:327` and `:353`) stay green.
- **A single short leg.** `_submit_for_fill` still falls back only on `_session_restricted`. An uncovered refusal on a lone option order raises. Only the combo path absorbs it, because only the combo carries its own cover.

### Caps untouched

`QUOTE_FRESHNESS_SECONDS` is still 300 and `DEFAULT_SPREAD_MAX` is still 0.10. The local combo fill calls the same `enforce_submission_quotes` with the same `spread_confirmed`, `contracts`, `multiplier`, and `spread_max`, so a quote with a missing or unparseable timestamp is still `Quoted unknown time` and still blocks the fill. `test_the_caps_are_untouched` and `test_a_missing_quote_timestamp_still_blocks_the_paper_combo_fill` pin both.

## Tests — `backend/tests/test_change12_order_message.py`

| Test | What it checks |
| --- | --- |
| `test_paper_account_fills_the_whole_combo_at_the_net_mid` | Four broker reasons (uncovered, not approved for uncovered, naked, market hours). One `mleg` submission, both legs in order, fill at the net mid 1.00, positions `+1 / -1`. |
| `test_paper_fill_note_is_the_broker_reason_then_the_mid` | The note is exactly the broker sentence then `The paper order filled at the mid.` None of the four holdback phrases appear. |
| `test_a_raised_uncovered_refusal_also_paper_fills` | An adapter that raises instead of returning a rejection dict takes the same path. |
| `test_real_brokerage_is_not_paper_filled` | `real_brokerage` raises, the message starts with the broker reason, carries the two combo sentences once, and carries neither short-leg sentence. No position opens. |
| `test_a_rejection_the_paper_book_cannot_absorb_keeps_one_holdback_sentence` | A buying-power refusal raises `ComboHeldBack` with the exact three-sentence message. `short leg was submitted` appears once. |
| `test_a_missing_quote_timestamp_still_blocks_the_paper_combo_fill` | A quote with `as_of=""` blocks before submission. Nothing filled. |
| `test_the_paper_combo_fill_runs_the_server_side_quote_check` | `enforce_submission_quotes` is called twice — once up front, once again on both leg symbols before the local fill — with the same spread arguments. |
| `test_the_caps_are_untouched` | 300 seconds, 10% spread. |
| `test_only_a_session_or_uncovered_refusal_is_paper_fillable` | The marker gate accepts closed-session and uncovered reasons and rejects `Broker rejected the order`, a buying-power reason, an unknown contract, and a vague `option trading level` sentence. |

Two existing tests gained a negative assertion so the double-append cannot come back:

- `test_stock_leg.py:311` — the combo rejection after a filled stock leg no longer contains `The short call was not submitted`.
- `test_apex_four_legs.py:544-545` — the real-brokerage market-hours rejection contains neither `The short call was not submitted` nor `The paper order filled`.

Existing coverage that had to keep passing: `test_stock_leg.py` (stock before the short call, the failed-option holdback, the single-leg buying-power holdback), `test_apex_four_legs.py` (one combo for four legs, rejection does not reach the shorts, market-hours paper fill, the real-brokerage reason), `test_change11.py::test_gamma_four_legs_execute_as_one_combo`, `test_executability.py`, `test_orders.py`, `test_options_execution.py`, `test_expiry_close.py`, `test_ws.py`, `test_change12_3c.py`.

## Results

Full backend suite, outside the sandbox, cwd `backend/`:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

**1747 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). 62.88s.

1806 tests collect. With the new file ignored, 1794 collect and 1735 pass, so the 12 added tests are the whole delta. The 59 skips are unchanged — same three files, same reasons (`test_all_100_strategies.py:109`, `test_iron_condor_msft_regression.py:222`, `test_platform_trade_card_invariants.py:282`).

`ruff check` on `fills.py` reports the same 10 pre-existing findings as the file at `297104c` (6 `F401`, 2 `RUF100`, 1 `F811`, 1 `I001`). No new finding was introduced.

## Not edited

`narrative_guard.py`, `strategy_engine.py`, `DeepScan.tsx`, the login pages, `alpaca.py`, `demo.py`, `executability.py`, `gate_config.py`, and `portfolio.py`.

## Requests for other owners

The note is readable in two places this agent owns: the transient `order.fill_note` attribute and the `note` field on the `fill` websocket frame. `POST /api/orders` in `backend/app/routers/portfolio.py:397-419` builds its own response dict and does not carry it, and `frontend/src/pages/Dashboard.tsx:150` ignores unknown fields on a `fill` frame. Whoever owns the route and the trade ticket should surface `fill_note` so the sentence reaches the screen on the HTTP response as well. Nothing in this change depends on that.
