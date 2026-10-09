# Change 12 — agent 4B

Branch: `change12/4B`. Worktree: `/Users/Mayank/Desktop/APEX-change12-4B`. Base: `change12/base` (`297104c`).

## What the trader saw

A defined-risk spread came back as one stacked refusal:

`Account not eligible to trade uncovered option contracts. The combo was not split into market orders. No short leg was submitted. The short call was not submitted. Remaining short legs were not submitted.`

The combo was already one limit. The extra sentences were appended even though no naked short was sent. On a paper account the broker's uncovered-option refusal, and a closed session, used to fill locally. That path had stopped for the combo.

## What changed

`backend/app/services/fills.py`

- Two or more option legs are still one limit combo at the net mid. A rejection is not split into single-leg orders, and the short legs are not sent alone.
- On a paper account, a closed session or an uncovered-option refusal fills the whole combo on the local book at that net mid. The same server-side quote check runs again before that local fill. A missing timestamp stays `Quote not current. Quoted unknown time.` The 300-second cap and the spread cap are unchanged.
- The notice is one line: the broker reason, then `The paper order filled at the mid.` It is `order.fill_note` and the fill event's `note`. It does not add `The short call was not submitted`.
- A real brokerage account keeps the broker rejection. That sentence says the combo was not split and no short leg was submitted. It does not say the short call was held back, and it does not paper-fill.
- A single short is not paper-filled on an uncovered-option refusal. A closed session can still paper-fill a single leg after the quote check, which is the covered-call path that already existed.
- `DemoAdapter.submit_order` was not changed. Combo paper fills do not call it. Single-leg demo fills still go through `enforce_submission_quotes` first.

## Tests

- `backend/tests/test_change12_order_message.py`: paper uncovered and closed-market combos fill at the mid with that one sentence; a real account does not; another combo rejection does not paper-fill and does not stack the short-call sentence; a missing timestamp or a spread wider than 10% of mid on the recheck blocks the local fill; a single short is not paper-filled when the broker refuses uncovered options; the 300-second cap and a missing timestamp stay strict.
- `backend/tests/test_stock_leg.py` and `backend/tests/test_apex_four_legs.py`: combo rejections that already say no short leg was submitted do not also say the short call was not submitted.

## Results

Backend, from `backend/` in this worktree, outside the sandbox:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

**1743 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). Baseline on `change12/base` was 1735 passed, 59 skipped. The eight new tests are the difference.

Alpaca and the demo adapter were not edited. The quote cap and the spread cap were not loosened. `narrative_guard.py`, `strategy_engine.py`, `DeepScan.tsx`, and Login were not edited.

The sentence is `order.fill_note` and the `note` field on the fill event. `POST /api/orders` still builds its own response and does not copy that field, so the trade ticket shows the confirmation because the order filled. The stacked refusal is gone.
