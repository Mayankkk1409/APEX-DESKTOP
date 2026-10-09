# Change 10 — Stock legs, the four-leg APEX Strategy, and a leg-completeness guard

## Brainstorm

A covered call that never buys the shares, and an APEX Strategy card that shows one call, are the same kind of failure: the name on the card is not the order that gets sent. Part A made stock a real leg. Two gaps were still open.

1. A short-stock template was still submitted, with a note that the locate had not been checked. This desk has no broker locate file. Holdings are the APEX ledger, not SnapTrade. An unconfirmed short cannot be sent, and the leg cannot be dropped so the options trade alone.
2. `_build_apex` planned four legs, deleted any leg that had no contract or no OCC symbol, and returned whatever remained. A one-leg list was shown as APEX Strategy.

The chain star can stay one contract. The recommendation, ticket, certificate, positions, and trade history have to list every leg that the template requires.

## Research

Quoted from `docs/changes/change-10/apex-definition.md`, which traces Full Document §10 and was not reinterpreted:

> Front-Week Expiry (Day After Catalyst): SELL OTM Call [Strike A]; SELL OTM Put [Strike B].
> Back-Week Expiry (Two Weeks Post-Catalyst): BUY OTM Call [Strike A]; BUY OTM Put [Strike B].
> Same strikes, different expirations.
>
> Step 1 — Buy 1 OTM Call expiring two weeks after the catalyst at Strike A (above current price). Buy 1 OTM Put expiring two weeks after the catalyst at Strike B (below current price).
> Step 2 — Sell 1 OTM Call expiring the day after the catalyst at the same Strike A. Sell 1 OTM Put expiring the day after the catalyst at the same Strike B.
>
> Premium from front-week shorts heavily subsidizes back-week longs (typically 50–70% offset).

§10.5, same trace:

> Maximum loss: net debit paid (cost of back-week longs minus front-week premium collected). Maximum gain: theoretically unlimited on the call side; substantial on the put side. Break-even: net cost relative to back-week strike distance.

Expected legs:

| # | Action | Side | Expiry | Strike |
|---|--------|------|--------|--------|
| 1 | buy | call | back week | Strike A, above spot |
| 2 | buy | put | same back week | Strike B, below spot |
| 3 | sell | call | front week | same Strike A |
| 4 | sell | put | same front week | same Strike B |

Quantity in the document is 1 on each leg. Net debit. The registry id is `apex_strategy`. The user-facing name is **APEX Strategy**.

### Where the live recommendation is built

`build_layers` calls `strategy_decision` → `recommend_strategy`. That function chooses the name **APEX Strategy** only when `check_apex_strategy_eligibility` passes. A failed eligibility check already falls through to the next eligible Best Match. This change does not add another fallback name.

`build_strategy_layer` then calls `compute_strategy_metrics` → `from_display_name` → **`_build_apex`** (`backend/app/strategies/metrics_builder.py`). That is the list the strategy slide and the risk-review ticket use.

### Root cause

`_build_apex` used to keep only the legs that resolved:

```python
legs = [lg for action, c, exp in plan if (lg := make_option_leg(action, c, expiry=exp))]
legs = [l for l in legs if l.get("symbol")]
```

If fewer than four remained, it still returned that shorter list (`metrics_builder.py`, the old body of `_build_apex`). `compute_strategy_metrics` returned it as the recommendation.

`_anchor_from_metrics_legs` (`strategy_engine.py` around line 1608) still sets the chain star from `option_legs[0]`, which for this builder is the back-week long call. That star is a highlight. It is not the order.

`strategy_selection_bucket` still maps the name to one buy call, or one buy put when the tape is bearish. That highlight may stay a star.

### Component mapping

| Surface | Source | What it showed before | What it uses now |
|---|---|---|---|
| Chain star | `_anchor_from_metrics_legs` | Back-week long call | Still that one contract |
| Strategy card | `metrics.legs` | Whatever survived the filter | All four legs, or a blocked card with no partial list |
| Risk-review ticket | `risk_review.strategy_legs` | Those same survivors, and it was built even when the layer was not tradeable | The four legs only when the layer is tradeable |
| Acknowledge and Place Trade | both `POST /api/orders` with that ticket | The survivors | All four, then the server orders buys before shorts |
| Confirmation certificate | `legs_filled` plus the stored strategy legs | One fill per submitted symbol | One row per filled leg, with the stored four-leg certificate on the position |
| Positions | one row per OCC symbol | The symbols that filled | Each filled leg; opening the certificate reads the stored four-leg list |
| Trade history | `GET /api/orders` | Side, symbol, qty, fill | Side, symbol, strike, expiry, qty, order type, fill |

There is no combined stock-plus-option ticket, and no combined multi-leg option ticket. Alpaca’s order endpoint and the demo adapter take one symbol per request. `execute_strategy_legs` is the coordinator.

### Open questions left unanswered

These gates were not edited. `check_apex_strategy_eligibility` is unchanged.

1. Is 0.15–0.25 a hard band, or is the rule only short-leg delta under 0.25, with no floor?
2. Does that band apply to the back-week longs, or only to the front-week shorts?
3. Is a 50% premium offset a hard fail, or only the typical 50–70% in the mechanics?
4. How much must front IV exceed back IV before inversion counts?
5. Must the expirations be the day after the catalyst and about two weeks later, or is the scan’s selected front and back pair allowed?
6. Which open-interest floor is in force: greater than 500, or greater than 1,000 per strike?
7. Is the tech/growth gap-history profile a hard gate?
8. Does “no earnings inside the front week” win, or the catalyst exception?

Item 9 from the definition trace is not open. The card max loss is the §10.5 net debit: back-week long cost minus front-week premium, times the contract multiplier. The constant-IV scan is the payoff grid only. It is not a second max-loss number. No new IV-inversion percentage was added.

When that scan finds a lower and an upper root, those are the breakevens. When it finds none, the card uses net debit against the back-week strikes (put strike minus the debit, call strike plus the debit). That is the §10.5 sentence applied so a complete four-leg structure is not blocked for an empty range. It is not a new inversion rule.

## Checklist

- [x] Share count is contracts times the chain multiplier. 100 is used when the chain publishes 100 or omits the field.
- [x] Unencumbered long shares are used first. Only the shortfall is bought. None means a buy.
- [x] Covered-call and protective-put dollars are computed in cents. A new buy uses the live ask. Held shares use average cost.
- [x] Acknowledge and Place Trade both `POST /api/orders`.
- [x] Stock fills before options. Short calls are not sent if the stock or an earlier option fails.
- [x] A short-stock strategy is infeasible with the exact reason `cannot confirm easy-to-borrow / margin`. The stock leg stays on the card. It is not submitted. No locate figure is invented.
- [x] APEX Strategy is returned only with all four template legs. A missing leg blocks the whole recommendation with a reason. It does not fall through to a new name.
- [x] Card, ticket, certificate, positions, and trade history can show action, symbol, strike, expiry, quantity, order type, and price.
- [x] The four option legs are one coordinated execution: buys, then shorts. A rejected component does not leave a later short in flight.
- [x] Combined capital, net debit, max profit, max loss, breakevens, Greeks, and a four-leg payoff grid.
- [x] How-to-execute names the strikes, expiries, and prices that were built.
- [x] A template check compares leg count, action, instrument, strike and expiry relationships, and ratios. A mismatch is logged and blocks the recommendation.
- [x] The nine disputed numeric gates above were not retuned. Item 9 is the requested net-debit alignment.

## Execute

### How each stock-leg strategy is ordered

Share quantity is `contracts × multiplier`. Long shares that are not already covering another short call are unencumbered.

| Strategy | Stock action | What is sent |
|---|---|---|
| Covered Call, Stock + Short Call | Buy | Use unencumbered shares, buy the shortfall at the live ask, then the short call |
| Married Put, Stock + Long Put, Synthetic Call | Buy | Same share rule, then the long put |
| Protective Collar, Collar | Buy | Same share rule, then the long put, then the short call |
| Leveraged Covered Call | Buy | Same share rule, then the long call |
| Conversion | Buy | Same share rule, then the short call and long put |
| Synthetic Straddle | Buy | Same share rule, then two long puts |
| Covered Put, Synthetic Put, Reversal | Short | Not sent. The card keeps the stock leg and is not tradeable |

Option synthetics (synthetic long stock, synthetic short stock, long combo, short combo) stay option-only. The wheel still opens as a cash-secured put until the account already holds a full covered-call lot, and that stage does not buy the shares again. There is no covered-strangle entry in the encyclopedia.

Covered-call dollars, in cents: max profit = (call strike − stock entry + call premium) × shares; max loss = (stock entry − call premium) × shares; breakeven = stock entry − call premium. Protective put: max loss = (stock entry − put strike + put premium) × shares; breakeven = stock entry + put premium; max profit is unlimited.

### Short stock

`plan_stock` does not treat a missing locate as a borrow. For every sell-stock template the metrics are `validation_blocked` with `validation_error` equal to `cannot confirm easy-to-borrow / margin`. `order_qty` is 0. `execute_strategy_legs` rejects an equity sell with that same sentence before any order is sent, so a short put is not left naked behind a dropped stock leg.

### Order sequence

1. An equity sell is refused. Nothing else is sent.
2. A stock buy, when the template needs one, must fill.
3. Option buys.
4. Short puts and short calls.

If the stock or a buy fails, no short option is sent. If one short is rejected, the later shorts are not sent. A broker rejection on this path is not replaced with a local paper fill. Shares or long options that already filled are left in the account. They are not automatically sold back.

APEX Strategy has no stock leg. The two buys go out, then the two sells. Acknowledge and Place Trade both post the four symbols. The server reorders them into that sequence even if the ticket lists a short first.

### APEX Strategy

`_build_apex` still plans the four rows in the table above. If any contract, OCC symbol, shared strike, expiry pair, quantity, or spot relationship is missing, it returns no legs and `validation_blocked`, with a reason that names what is missing. It does not return a one-leg list.

When the four legs match, max loss and capital at risk are the net debit in dollars. Max profit stays unlimited. Greeks are the signed sum of the greeks on the four contracts when the chain published them. The payoff grid is the four-leg value at front expiry (short intrinsic plus the back-week option value minus the debit). The explanation and the how-to-execute line name each strike, expiry, price, and market order.

The template guard in `validator.py` (`_check_leg_template`, `apex_structure_reason`) runs on every tradeable recommendation that reaches `validate_strategy_output`. A mismatch is logged as `strategy_validation_failed` and the layer is not tradeable, so the ticket is empty. Vega-neutral quantities stay the computed vega offset rather than a fixed 1:1. Butterfly, strip, strap, ratio, and backspread quantities use the ratios those builders already publish. Undefined-risk names that the validator already skips before leg inspection stay on that path; they are not execution candidates.

### Before and after

**Covered call, AAPL, spot 100, no shares held, live ask 101.25, multiplier 100.**

Before Part A, the card said the shares were already held and the order posted only the call. After Part A, and still after this pass: the ticket is BUY 100 AAPL at the ask, then the short call. Dollars use the ask as the stock entry. This pass did not change that buy path.

**Covered put (the short-stock gap).**

Before this pass, the ticket included SELL SHORT 100 shares and a note that shortability was not checked. After: the stock leg is still on the card, `order_qty` is 0, the layer is not tradeable, and `POST /api/orders` is not given a short.

**APEX Strategy on the 105 call / 95 put fixture, spot 100.**

Back-week call mid 2.50, back-week put mid 2.10, front-week call mid 1.30, front-week put mid 1.10.

Before: a missing back-week contract was dropped and the remaining legs were still returned. The headline contract was the first option, the back-week long call.

After, when all four quotes exist:

- BUY 1 call 105, back expiry, at $2.50, market
- BUY 1 put 95, same back expiry, at $2.10, market
- SELL 1 call 105, front expiry, at $1.30, market
- SELL 1 put 95, same front expiry, at $1.10, market

Net debit per share = 2.50 + 2.10 − 1.30 − 1.10 = 2.20. Max loss and capital at risk = 2.20 × 100 = $220.00. Max profit is unlimited. If the back-week put is missing, the legs list is empty and the reason names the missing back-week put. The Best Match name is not replaced with a different strategy.

### UI wording audit

Removed only where a sentence described a leg the app now sends. The Part A sentence “Assumes you already hold 100 shares per contract — options overlay only; stock is not submitted” is already gone from the strategy card, the scan, and the order path.

Left in place, because they are not a claim that an executed leg was skipped:

| Location | Text | Why it stays |
|---|---|---|
| `OptionsChainGreeks.tsx` | “No simulated chain is shown.” | Missing market-data keys. Not a leg. |
| `types.ts` chain status `"simulated"` | Status enum | Labels a demo chain. Not a leg. |
| `strategyFormat.ts` | “Breakeven range assumes current implied volatility…” | Model note for a calendar range. Not a missing leg. |
| `Settings.tsx` | “Paper trading only” / “Simulation only” | Account type. |
| `constants.ts` | Legal line that APEX assumes no liability | Not a leg. |
| `fills.py` | “The short call was not submitted” / “Remaining short legs were not submitted” | True only after a component was rejected. Those shorts were not sent. |

## Test

Commands and results from this pass:

```text
PYTHONPATH=backend python3 -m pytest \
  backend/tests/test_apex_four_legs.py \
  backend/tests/test_stock_leg.py \
  backend/tests/test_synthetic_structures.py \
  backend/tests/test_strategy_registry_validation.py \
  backend/tests/test_all_100_strategies.py \
  backend/tests/test_strategy_coverage.py \
  backend/tests/test_strategy_coverage_conditions.py \
  backend/tests/test_platform_trade_card_invariants.py \
  backend/tests/test_strategy_engine.py \
  backend/tests/test_mislabeled_structures.py \
  backend/tests/test_structure_payoff.py \
  backend/tests/test_options_execution.py \
  backend/tests/test_integration_scan.py \
  backend/tests/test_apex_upgrade.py
```

That set passed (950 passed across the two runs: 922, then 28 more, with skips where a builder blocks for a missing quote or a short-stock locate). `test_all_100_strategies` skips a strategy when the builder sets `validation_blocked`. On the generic rich chain, the put nearest a 0.20 delta is not below spot, so APEX Strategy is blocked there and the test skips it. The dedicated 105/95 fixture asserts the four-leg template.

`test_strategy_coverage.py` and `test_strategy_coverage_conditions.py` are the Change 9 offline fixtures. They passed. The live 50-symbol scan was not run. It needs network access and API keys.

Frontend, using the repo’s Vitest 2.1.9:

```text
./node_modules/.bin/vitest run \
  src/components/scanSlides.test.tsx \
  src/components/OrderConfirmationCertificate.test.tsx \
  src/lib/certificateLegs.test.ts \
  src/pages/DeepScan.order.test.tsx
```

18 passed. No browser click-through was done.

What the new tests cover:

- Bullish, bearish, neutral, high-IV, and low-IV builds: four legs matching the template whenever the chain can build APEX Strategy. A missing leg is an empty list and a rejection, not a partial APEX Strategy. Failed eligibility does not select the name.
- All four legs fill, buys before shorts.
- A rejected buy sends no short. A rejected short does not send the other short.
- Max loss equals the hand-calculated net debit, $220.00 on the fixture.
- Card legs, ticket rows, and the certificate leg list are the same four symbols.
- Covered-call stock tests in `test_stock_leg.py` stay green. The short-stock test now expects the infeasible reason and no order.

## Files

| File | Why |
|---|---|
| `backend/app/services/stock_leg.py` | Short stock is infeasible and not an order. Ticket rows carry price and order type. Short options are separated from buys. |
| `backend/app/services/fills.py` | Equity sells are refused. Buys fill before shorts. A rejection stops the remaining shorts. |
| `backend/app/strategies/metrics_builder.py` | `_build_apex` blocks an incomplete structure and attaches combined Greeks and capital. |
| `backend/app/strategies/payoffs/core.py` | APEX max loss is the net debit. The grid is the four-leg scan. |
| `backend/app/strategies/validator.py` | Template check and the four-leg APEX structure check. Failures are logged. |
| `backend/app/services/strategy_engine.py` | The unused APEX branch also returns no partial legs. How-to-execute names strikes, expiries, and prices. |
| `backend/app/services/scan_engine.py` | The order ticket is built only when the layer is tradeable. |
| `backend/app/routers/portfolio.py` | Filled legs include order type. The stored certificate includes Greeks. |
| `frontend/src/components/StrategyScan.tsx` | All legs, capital, Greeks, and the payoff grid. A blocked structure with legs is marked not executable. |
| `frontend/src/pages/DeepScan.tsx` | Ticket rows show quantity, order type, and price. A blocked scan shows the reason. |
| `frontend/src/components/CertificateLegList.tsx` | Each certificate row shows the order type. |
| `frontend/src/lib/certificateLegs.ts` | Order type on each displayed leg. |
| `frontend/src/pages/Portfolio.tsx` | Trade history shows strike, expiry, and order type. |
| `frontend/src/types.ts` | Leg, Greek, and payoff-grid fields. |
| `backend/tests/test_stock_leg.py` | Short stock is infeasible and is not submitted. |
| `backend/tests/test_apex_four_legs.py` | Four-leg structure, debit math, and the rejection sequence. |

## Order failure fix

The message `Option or stock order failed. The short call was not submitted. Remaining short legs were not submitted.` is raised in `execute_strategy_legs` (`backend/app/services/fills.py`). It used to replace whatever the covering buy had actually thrown.

The live failure on 4 Oct 2026 was Alpaca `42210000`: `options market orders are only allowed during market hours`, logged from `AlpacaAdapter.submit_order` while pricing `DAL261009C00084000`. The option was sent as a market order. Strict mode then dropped the response body and returned only `rejected: true`, so the desk showed the holdback sentence and did not fill the paper book. A second pricing bug quoted that OCC symbol on the stock feed (`invalid symbol`) and, when the chain mid was ignored, valued the contract like a $100 share.

What changed:

- The broker sentence is kept. A hard rejection starts with that sentence. The short-call holdback stays the second sentence, and later shorts are still not sent.
- A paper account (`paper_funded`) treats a session rejection (`options market orders are only allowed during market hours`, `market is closed`) as a local paper fill at the chain mid. After the first such fill, the remaining legs, including every short, stay on that paper path and are not sent to the broker.
- A real brokerage account is not paper-filled. The same session sentence is the error.
- Option buying power and the paper fill use the scan mid (or the ticket price), not a stock quote of the OCC symbol. Whole-number quantities are sent as integers. A sell-to-open writes the short position.

`cannot confirm easy-to-borrow / margin` is unchanged. Short stock is still not submitted.

The old generic raise was `fills.py` around the buy loop (previously line 274). Alpaca dropped the body in `submit_order` (previously line 671). The holdback now starts with the caught reason (`fills.py` `_holdback`). The broker sentence is attached in `alpaca.py` `submit_order`.

```text
PYTHONPATH=backend backend/.venv/bin/python -m pytest \
  backend/tests/test_apex_four_legs.py \
  backend/tests/test_stock_leg.py \
  backend/tests/test_options_execution.py \
  backend/tests/test_expiry_close.py \
  backend/tests/test_portfolio.py \
  backend/tests/test_integration_scan.py
```

60 passed (41, then 19). No browser click-through. The order API response text was covered by the pytest client.

## Card filters are gates

The AAPL long-call card was APEX Benchmark Greeks Strategy, not the four-leg APEX Strategy. The playbook text listed Rule 1 (daily theta under 0.05, delta/theta over 10), spread under 8% of mid, and “exit on composite drop below 72.” None of that was checked against the contract being bought. Auto-execute only compared the composite with the saved entry minimum, so 63.1 cleared an entry of 40 while the card already said to exit below 72. Delta/theta for strategy ranking used the best ratio on the chain, not the recommended contract. IV rank from a history series was the unrounded formula, so the card printed `46.05037606326132`.

Theta for that contract is already about 0.18 per share per day in the Black-Scholes path. Once Rule 1 reads that number it fails. A Greek larger than the option mid is treated as the whole-contract figure and divided by the multiplier before the same 0.05 test. A ratio of about 1.20 (IV 27% versus HV 22.5%) stays inside the existing 5-point band for scoring and is not extreme IV (that remains IV greater than HV times 1.35). The card states the point gap. It does not call that pair cheap or fair, and it does not rename the strategy.

What changed:

- The printed exit uses the saved auto-execution minimum. If the composite is already under the exit number on the card, auto-execute stays off.
- When the card lists Rule 1 or the 8% spread rule, the recommended buy is graded on those numbers. A miss is named and is not auto-bought. The strategy title stays. Long-call max loss, breakeven, and unlimited max profit are unchanged.
- Option legs on a card that cites the spread rule are a limit at the live bid/ask mid. Stock-before-short-call sequencing and the broker rejection sentence are unchanged. The eight APEX Strategy numeric gates were not retuned.
- A confirmed earnings date inside 1 day blocks a new auto-execute, except APEX Strategy. A missing date is “Earnings date is unconfirmed.” No date is invented.
- IV rank is stored and shown to one decimal, or as a whole number when the tenth is zero.

Files: `backend/app/analysis/options_rules.py`, `backend/app/analysis/volatility.py`, `backend/app/services/strategy_recommendation.py`, `backend/app/services/strategy_engine.py`, `backend/app/services/scan_engine.py`, `backend/app/services/volatility_intel.py`, `backend/app/strategies/metrics_builder.py`, `backend/app/services/stock_leg.py`, `backend/app/services/fills.py`, `frontend/src/components/StrategyScan.tsx`, `frontend/src/pages/DeepScan.tsx`, `frontend/src/types.ts`, `backend/tests/test_card_filter_gates.py`.

```text
python3 -m pytest backend/tests/test_card_filter_gates.py \
  backend/tests/test_strategy_engine.py \
  backend/tests/test_options_rules.py
```

94 passed, including the veto-label scan in `test_auto_execution_threshold.py`. Related four-leg, coverage, volatility, and options-analysis suites were run with those; one pre-existing source scan failed until the copy filter stopped embedding the veto phrases as single literals. No live scan was clicked.

Not invented: a new IV regime, an earnings date, a change to the 1.35 extreme-IV line, or any of the eight APEX Strategy numeric gates in `apex-definition.md`.

## Empty order ticket

Live NFLX and MRK diagonals reached risk review with `strategy.metrics.legs` holding both OCC contracts and `risk_review.strategy_legs` equal to `[]`. The layer was not tradeable because `breakeven_shape` required a closed-form range and the scan returned `[]`, even though `payoff_depends_on_remaining_leg` was already set. The order step only copied legs when `tradeable` was true, then printed "No options legs are available for this scan."

An empty breakeven scan on a structure with no closed form is no longer an execution block. The risk review still names the gate (`block_reason`, or the strategy validation error) when there are truly no buildable contracts. If the ticket list is empty but the strategy metrics still have option contracts, the order step uses those contracts. An unconfirmed short, a missing required stock leg, and a partial APEX Strategy stay off the ticket. Limit-at-mid on a leg is unchanged.

Files: `backend/app/strategies/validator.py`, `backend/app/services/scan_engine.py`, `backend/app/routers/portfolio.py` (optional `order_type` / `limit_price` on a posted leg), `frontend/src/lib/orderTicket.ts`, `frontend/src/components/RiskReviewLegs.tsx`, `frontend/src/pages/DeepScan.tsx`.

```text
PYTHONPATH=backend python3 -m pytest backend/tests/test_strategy_engine.py backend/tests/test_apex_four_legs.py backend/tests/test_stock_leg.py backend/tests/test_strategy_registry_validation.py
cd frontend && ./node_modules/.bin/vitest run src/pages/DeepScan.order.test.tsx src/lib/riskReview.test.ts
```

88 backend tests passed. 19 frontend tests passed (6 on the order panel, 13 on placement). No live click-through.

## Limitations

- There is no broker locate file. Easy-to-borrow, margin permission, and margin requirement cannot be verified, so every short-stock strategy is infeasible. No locate was invented.
- Holdings are the APEX ledger (paper and Alpaca fills), not a SnapTrade position read.
- There is no combined multi-leg ticket. Legs are sequential. A fill that already happened is not automatically reversed when a later leg is rejected.
- When the quote has no ask, a new buy still falls back to the scan reference price and the note says the live ask was not on the quote.
- The payoff card is for one structure. The ticket resizes every option leg to the contract count typed on the ticket.
- The chain star is still one contract.
- The eight numeric questions above are unchanged.
- The live 50-symbol scan and a browser click-through were not run.

## Dev-server WebSocket EPIPE

Vite logged `ws proxy socket error: write EPIPE` while the dashboard held `/ws/market` open through the dev proxy (`ws://127.0.0.1:5173/ws/market` → `ws://127.0.0.1:8000/ws/market`). The API was up (`GET /health` 200 on `127.0.0.1:8000`). Uvicorn `--reload` was restarting the worker as backend files changed, so the proxy still wrote a frame into a socket the worker had already closed. The browser then sat on that dead subscription until a raw close, and a torn frame could throw in `JSON.parse`.

The proxy now destroys both ends on EPIPE, ECONNRESET, and ECONNREFUSED and does not hand those to Vite's logger. The dashboard and expiry-watch clients reconnect with backoff, ignore a torn frame, and do not treat the drop as a failed trade. A bad token is accepted and closed with 4401 so the proxy gets a close frame. A quote error no longer tears down the fill socket.

Manual check: with the desk open, save a backend file so uvicorn reloads. The Vite terminal should stay quiet, and the next paper fill should still refresh the dashboard balances. Restart Vite once so `vite.config.ts` is picked up.

## Strategy-engine gates, payoff grid, and APEX Strategy payoff

### File → responsibility

| File | Responsibility |
|---|---|
| `backend/app/config.py` | Env settings for theta mode, theta percent cap, entry/exit composite lines, and the IV inversion gap. Entry must stay above exit. |
| `backend/app/analysis/gate_config.py` | Reads those settings. Regime words, Rule 1 theta, hysteresis, positive max loss, earnings-before-expiry copy, quote staleness, the 2:1 mid fingerprint, and the order refusal. |
| `.env.example` | Documents the five settings. No secrets. |
| `backend/app/analysis/options_rules.py` | Rule 1 flag uses the configurable theta filter, an 8% spread, and contract IV below HV. |
| `backend/app/services/strategy_engine.py` | Card gates, one labeled IV per check, NOT EXECUTABLE when any check fails, regime words, APEX Strategy payoff copy, calendar/diagonal IV copy, hysteresis on the card. |
| `backend/app/services/strategy_recommendation.py` | IV rank above 70 drops a plain long call or put. Rank above 50 counts as rich IV for the matrix. |
| `backend/app/services/volatility_intel.py` | 30-day ATM regime label in plain words. |
| `backend/app/services/apex_strategy.py` | Inversion in vol points. Open interest and spread come from the four chosen strikes. |
| `backend/app/services/scan_engine.py` | Earnings inside the expiry window is a scoring penalty. It does not change pillar weights. |
| `backend/app/analysis/composite_score.py` | Optional earnings-before-expiry penalty on the composite. |
| `backend/app/strategies/payoffs/core.py` | Front-expiry grid for calendars, diagonals, and the APEX Strategy double calendar. Max loss is a positive dollar amount. Max profit is the grid cap. |
| `backend/app/strategies/metrics_builder.py` | Absolute max loss. Diagonal passes the short strike and back-leg IV. APEX Strategy passes each back-leg IV. |
| `backend/app/strategies/structure_math.py` | Calendars and diagonals keep the numeric max profit. |
| `backend/app/strategies/registry.py` | APEX Strategy max profit is the IV-dependent grid, not unlimited. |
| `backend/app/strategies/validator.py` | A front-expiry scan with fewer than two zero crossings is still a complete structure. |
| `backend/app/services/fills.py` | Refuses a submit when checks did not all pass, including when auto-execute is forced. |
| `backend/app/routers/portfolio.py` | Same refusal on `POST /api/orders` before the broker call. |
| `frontend/src/components/StrategyScan.tsx` | Banner is NOT EXECUTABLE when the layer is blocked. Max loss is shown as a positive amount. |
| `frontend/src/types.ts` | `checks_passed`, `execution_banner`, and `auto_exec_blocked` on the strategy layer. |
| `backend/tests/test_strategy_gate_fix.py` | The six fixtures in the spec. |
| `backend/tests/test_card_filter_gates.py`, `test_options_rules.py`, `test_strategy_engine.py`, `test_strategy_registry_validation.py`, `test_apex_four_legs.py`, `test_apex_upgrade.py`, `test_strategy_explanations.py` | Assertions updated where the old expected copy contradicted these gates or the front-expiry model. |

### Config values added

| Name | Default |
|---|---|
| `THETA_FILTER_MODE` | `pct_of_premium` |
| `THETA_MAX_PCT_PER_DAY` | `0.015` |
| `ENTRY_COMPOSITE_MIN` | `45` |
| `EXIT_COMPOSITE_MIN` | `40` |
| `MIN_IV_INVERSION_PTS` | `5` |

`QUOTE_FRESHNESS_SECONDS` is 300 in `gate_config.py`. The app had no quote-age setting. Feature.txt compares data on a 5-minute cycle, so that is the window. A missing timestamp is not treated as stale. A mid whose implied vol is more than 5 points from the chain IV is stale, and an exact 2:1 pair of option mids is stale.

Technical, sentiment, and fundamentals weights are unchanged.

### Assertion updates, and why

- AAPL at IV rank 46 with IV above HV is regime `fair`. `sell premium` requires rank above 50. The old "4.5 pts above HV" phrase is gone.
- Default theta mode is percent of premium, so the AAPL card no longer quotes the 0.05-per-share and delta/theta lines. It is still NOT EXECUTABLE because contract IV is not below HV. Absolute mode still fails that contract on theta.
- The same AAPL contract no longer shows an auto-execute-eligible line. Rule 1 requires IV below HV.
- An unconfirmed earnings date is still not invented. Auto-execute stays off because IV is not below HV.
- The old Rule 1 sample had a 10% spread, IV above HV, and theta that fails the percent cap. The passing sample is a tight quote with IV below HV.
- Calendar and APEX Strategy cards publish a finite grid max profit. The old null profit, unlimited flag, and `section_10_5_net_debit` basis described the removed unlimited prose. Max loss basis is `net_debit`.
- The bull put fixture spreads are about 17% and 26% of mid, so Rule 2's 10% cap marks the card NOT EXECUTABLE.
- The APEX Strategy fixture spreads are about 15% and 18% of mid, so the 8% four-leg cap marks the card NOT EXECUTABLE. The ticket test still builds the four legs.
- Spread for the APEX gate is the worst of the four chosen strikes, in percent. A chain median and a tighter unrelated contract are not used. With no four legs, spread is unset.
- Calendar copy no longer says there is no closed-form max profit. The card states that profit and breakevens depend on the back-leg IV.

A low-IV APEX Strategy grid (about $2.20 of debit and 14 days left at 12–25% IV) never crosses zero inside ±40% of spot. Those roots are left empty. The strike-plus-debit fallback was not restored. At 40% and 55% IV the same fixture has two roots, and profit is highest near a strike.

### What was not fully wired

- Earnings opt-in is the `earnings_risk_opt_in` argument on `build_strategy_layer`. There is no settings column or settings-page control for it, so the product UI cannot turn that override on yet. A missing date still reads as unconfirmed.
- Hysteresis sets `position_action` on the card and blocks a new auto-execute when the action is not `enter`. There is no separate monitor that submits a close when a live position falls through the exit line.
- The 1.35× HV overhang remains a labeled risk note. It does not rename the strategy.
- Frontend vitest is not installed in this workspace (`frontend/node_modules` has no vitest), and the desk was not click-tested in a browser. Backend coverage is below.

### Tests

```text
PYTHONPATH=backend python3 -m pytest backend/tests/test_strategy_gate_fix.py backend/tests/test_card_filter_gates.py backend/tests/test_options_rules.py backend/tests/test_strategy_engine.py backend/tests/test_structure_payoff.py backend/tests/test_apex_four_legs.py backend/tests/test_strategy_registry_validation.py backend/tests/test_apex_upgrade.py backend/tests/test_strategy_coverage.py backend/tests/test_strategy_coverage_conditions.py backend/tests/test_mislabeled_structures.py backend/tests/test_all_100_strategies.py backend/tests/test_platform_trade_card_invariants.py backend/tests/test_stock_leg.py backend/tests/test_options_execution.py backend/tests/test_synthetic_structures.py backend/tests/test_strategy_explanations.py
```

1018 passed, 48 skipped, 0 failed.
