# APEX Strategy definition

Read-only trace. Product code was not changed.

Authoritative prose is Full Document §10 and the worked four-leg card in §3.6, plus the gate table in `docs/RECOMMENDATION_ENGINE.md`. The registry id is `apex_strategy`. The user-facing name is **APEX Strategy**.

Expected leg count: **4**.

Drop point for the live recommendation list: **`_build_apex`** in `backend/app/strategies/metrics_builder.py`. Missing contracts and legs without an OCC symbol are removed there. Whatever remains is what the strategy slide and the risk-review leg list render. A complete chain is not reduced to one leg in that function.

The header still shows one contract because **`_anchor_from_metrics_legs`** in `backend/app/services/strategy_engine.py` keeps only `option_legs[0]`. For this builder that first leg is the back-week long call.

## Quoted definition

Full Document §10, mechanics (diagram and steps):

> Front-Week Expiry (Day After Catalyst): SELL OTM Call [Strike A]; SELL OTM Put [Strike B].
> Back-Week Expiry (Two Weeks Post-Catalyst): BUY OTM Call [Strike A]; BUY OTM Put [Strike B].
> Same strikes, different expirations.
>
> Step 1 — Buy 1 OTM Call expiring two weeks after the catalyst at Strike A (above current price). Buy 1 OTM Put expiring two weeks after the catalyst at Strike B (below current price).
> Step 2 — Sell 1 OTM Call expiring the day after the catalyst at the same Strike A. Sell 1 OTM Put expiring the day after the catalyst at the same Strike B.
>
> Premium from front-week shorts heavily subsidizes back-week longs (typically 50–70% offset).

Full Document §3.6 worked card (illustration, not a required ticker or strike):

> LEG 1 (Long): Buy the later expiry call at Strike A.
> LEG 2 (Long): Buy the later expiry put at Strike B.
> LEG 3 (Short): Sell the earlier expiry call at Strike A.
> LEG 4 (Short): Sell the earlier expiry put at Strike B.
> Net debit. The example card also checks front-week delta &lt; 0.25 on the short legs, bid/ask &lt; 8% of mid on all four legs, and OI &gt; 500 on all strikes.

Full Document §10.4 entry conditions:

> Days to catalyst 5–10 calendar days. Front-week IVR &gt; 70. Front-week IV significantly higher than back-week IV. ADV &gt; 5M shares; option OI &gt; 1,000 per strike. Bid/ask on all 4 legs &lt; 8% of mid. Stock profile: highly liquid tech/growth with documented gap history.

Full Document §10.5 risk:

> Maximum loss: net debit paid (cost of back-week longs minus front-week premium collected). Maximum gain: theoretically unlimited on the call side; substantial on the put side. Break-even: net cost relative to back-week strike distance.

`docs/RECOMMENDATION_ENGINE.md` (same four legs; numeric gates the eligibility module copies):

> 4 legs: buy back-week call and put, sell front-week call and put at the same strikes. Delta 0.15–0.25 OTM on each wing. Front-week premium ≥ 50% of back-week debit. Front-week IVR &gt; 70. Front IV &gt; back IV. ADV &gt; 5M. Per-strike OI &gt; 1,000. Spreads &lt; 8% of mid on all four legs. Catalyst 5–10 calendar days. Every criterion must pass.

Registry (`backend/app/strategies/registry.py`, id `apex_strategy`):

> buy call, buy put, sell call, sell put. Each leg is tagged `wide_otm` and `two_distinct`. `max_profit_type` is `unlimited`. Payoff ref is `payoff_apex_strategy`.

Playbook text in `strategy_engine.py` matches Step 1 and Step 2 above.

## Expected leg list

| # | Action | Side | Expiry | Strike |
|---|--------|------|--------|--------|
| 1 | buy | call | back week (about two weeks after the catalyst) | Strike A, OTM, above spot |
| 2 | buy | put | same back week | Strike B, OTM, below spot |
| 3 | sell | call | front week (day after the catalyst) | same Strike A |
| 4 | sell | put | same front week | same Strike B |

Quantity on each leg in the document is 1. Call and put strikes differ from each other. The call strike is shared across the two expirations. The put strike is shared across the two expirations.

## Where the live recommendation is built

`build_layers` (`backend/app/services/scan_engine.py`) calls `strategy_decision` → `recommend_strategy`. That function only chooses the name **APEX Strategy** when `check_apex_strategy_eligibility` passes and a catalyst is active. It does not build legs.

`build_layers` then calls `build_strategy_layer` (`strategy_engine.py`), which calls `compute_strategy_metrics`. That returns the registry builder immediately:

`from_display_name` → `build_registry_metrics` → **`_build_apex`**.

The later APEX block inside `compute_strategy_metrics` is not on this path. The registry result already has a `legs` key and `payoff_apex_strategy`.

`_build_apex` plans the four rows in the table above, targeting about 0.20 delta on the front chain and the same strikes on the back chain. It then drops rows:

```python
legs = [lg for action, c, exp in plan if (lg := make_option_leg(action, c, expiry=exp))]
legs = [l for l in legs if l.get("symbol")]
```

`make_option_leg` returns nothing when the contract is missing. The second line removes a leg with no OCC symbol. If fewer than four legs remain, `_build_apex` still returns that shorter list with `validation_blocked`. `compute_strategy_metrics` returns it as-is.

`build_layers` copies those remaining legs into `strategy_legs` (still skipping a row with no OCC symbol or an action other than buy/sell). `StrategyScan` renders every entry in `metrics.legs`. The risk-review list renders `strategy_legs`. So a partial build is what the UI shows: one surviving leg is one row, not a second hidden filter.

## Why the card can still show one part when four legs exist

`_anchor_from_metrics_legs` replaces the recommended contract with the first option leg only:

```python
primary = option_legs[0]
```

`_build_apex` appends the back-week long call first, so the anchor is that one call. `StrategyScan` prints it as “Anchor leg” and still lists the other legs underneath when they were built.

Before that overwrite, `strategy_selection_bucket` (`options_analysis.py`) maps the name **APEX Strategy** to a single bucket: buy a call, or buy a put when direction is bearish. `pick_recommended_contract` then chooses one front-expiry contract. That is a one-contract chain highlight, not the four-leg structure.

`matchesRecommended` on the chain ladder also ignores a highlight whose expiry is not the expiry on screen. Back-week legs do not mark on the front-week chain.

## Contradictions

Documented structure and `_build_apex` agree on four legs, sides, long back / short front, and shared strikes. These do not:

- **Delta.** §3.6 and §5.1 say front-week short delta &lt; 0.25 or ≤ 0.25. They do not state a 0.15 floor. `RECOMMENDATION_ENGINE.md` and `check_apex_strategy_eligibility` require absolute delta from 0.15 through 0.25 on the call and the put. The builder aims at 0.20 and does not reject a strike outside that band; the eligibility object does.
- **Offset.** §10 mechanics say the subsidy is typically 50–70%. §10.4’s entry table does not list offset. The engine doc and `FRONT_PREMIUM_OFFSET_MIN` (0.50) make 50% a hard fail.
- **IV inversion.** §10.4 says front IV must be “significantly” higher. The code treats any front IV greater than back IV as inverted.
- **Expiries.** The document fixes the front expiry to the day after the catalyst and the back expiry to about two weeks later. `_build_apex` uses the scan’s selected front expiry and whatever back-month chain was loaded.
- **Open interest.** The §3.6 card says OI &gt; 500. §10.4 and the engine doc say OI &gt; 1,000 per strike. The code threshold is 1,000, but `build_apex_strategy_input_from_scan` takes the minimum OI across every contract in the payload, not only the four chosen strikes.
- **Spread.** The document requires all four legs under 8% of mid. The scan input keeps the tightest spread in the whole chain (`min`), so one tight unrelated contract can pass the gate.
- **Registry tags.** Each leg is `wide_otm` / `two_distinct`. That does not record “same strike on the two expirations.” The prose and `_build_apex` do require that match.
- **Max loss.** §10.5 defines max loss as the net debit. `apex_strategy_payoff` scans value at front expiry under constant IV and can publish a different loss. `payoff_apex_strategy` is not in the no-closed-form set, so that scanned loss can appear on the card while max profit stays unlimited.
- **Chain recommendation.** `strategy_selection_bucket` expresses this four-leg name as one long call or one long put.

## Questions (not resolved here)

1. Is 0.15–0.25 a hard gate on both wings, or is the document’s rule only “short-leg delta under 0.25,” with no floor?
2. Does that delta band apply to the back-week longs, or only to the front-week shorts?
3. Is a 50% premium offset required, or only the typical 50–70% described in the mechanics?
4. How much must front IV exceed back IV before inversion counts?
5. Must the expirations be the day after the catalyst and about two weeks later, or is any nearer/farther pair allowed?
6. Which OI floor is in force: &gt; 500 on the example card, or &gt; 1,000 per strike in §10.4?
7. Is the “tech/growth with documented gap history” profile a hard gate? Nothing in the eligibility module checks it.
8. The §3.6 card says no earnings inside the front-week window, while the structure is for a catalyst 5–10 days out and the front expiry is the day after that catalyst. Which sentence controls?
9. Should the card show max loss as the net debit (§10.5) or as the constant-IV scan from `apex_strategy_payoff`?
