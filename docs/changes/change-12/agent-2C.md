# Change 12 — agent 2C

Branch: `change12/2C`, started from `change12/base` at `51dbcf9c24269a242ce892b5d8fa375c1360886f`.

Scope: Spec D1 and D3. Files owned by 2C only. `backend/app/contracts.py` was not edited.

## D1 — required catalog fields

Knowledge base version is **12.0**. The Change 11 v2 changelog row and the verbatim Rule 1, Rule 2, and Gamma Trampoline™ paragraphs are unchanged.

Every registry strategy, plus `apex_benchmark_greeks_buy`, `apex_benchmark_greeks_sell`, and `gamma_trampoline`, stores:

- legs template
- outlook
- vega, theta, and gamma sign (`long` / `short` / `positive` / `negative` / `not_stated` / `none`, and the other allowed tokens)
- ideal IV regime
- DTE window, with `dte_min` / `dte_max` only where the product already states a window
- max profit, max loss, and breakeven formulas
- assignment note
- entry, management, and exit text
- approval class (brokerage class, not an OCC number)
- reference naming OCC, the Options Industry Council, or Cboe
- version `12.0`

`validate_knowledge_base()` is the startup check in `backend/app/main.py` and the CI check. `validate_entries()` fails when a required field is blank. `test_validator_fails_when_a_required_field_is_removed` blanks each required field on `long_call`.

Windows that are actually stored:

| Entry | Window | Source already in the product |
| --- | --- | --- |
| Rule 1 buy (`apex_benchmark_greeks_buy`, and the registry id that points at it) | 30 to 90 | Change 11 Rule 1 setting |
| Rule 2 sell (`apex_benchmark_greeks_sell`) | 30 to 45 | Change 11 Rule 2 setting |
| Married Put | 30 to 45 | Playbook execution text |
| Short Iron Condor | 30 to 45 | Playbook execution text |
| Long call LEAPS, long put LEAPS, long straddle LEAPS | at least 365 | `LEAPS_MIN_DTE` |
| Gamma Trampoline™ | 5 to 10 calendar days before earnings | Change 11 earnings window |

Every other strategy has `dte_min` and `dte_max` of null and the sentence "No product DTE window is stated." That is not a new gate.

Gamma Trampoline™ is a separate catalog row. `entry_for("Gamma Trampoline™")` returns that row. The registry id `apex_strategy` stays titled **APEX Strategy**. `double_calendar` stays titled **Double Calendar**. The Change 11 classifier sentence is on both the trademark row and the APEX Strategy row: the trademark is used only when the earnings gates pass.

Greek signs are copied from the existing greek sentences. A sign that sentence does not name is `not_stated`. Approval text says OCC's *Characteristics and Risks of Standardized Options* describes the payoff and does not assign a numeric approval level. No page is pasted.

## D3 — scenarios

Recorded OPRA or Alpaca chains: **none**. The QA CSV has ticker, expiry, strategy, and leg count. It has no bid or ask.

**83** registry strategies have **5** stated-premium expiry scenarios. The premiums are the inputs of the OCC expiry identity (long value is intrinsic minus premium; short is the reverse). Each grid point matches `multi_leg_payoff_at_expiry` within **$0.01**. Option-only rows also match `expiry_pnl`. These are not market quotes and they do not name a scan winner.

**17** registry strategies are honestly incomplete. They are listed in `backend/tests/golden/stated_premiums.py` and are not given a passing payoff assertion.

| Strategy | Reason |
| --- | --- |
| `calendar_spread`, `calendar_put_spread`, `calendar_call_spread`, `diagonal_spread_bullish`, `diagonal_spread_bearish`, `diagonal_call_spread`, `reverse_calendar`, `double_calendar`, `double_diagonal`, `calendar_straddle`, `vega_neutral_spread`, `jelly_roll`, `apex_strategy`, `poor_mans_covered_call` | Two expirations. Near-expiry value depends on the later option's IV. No recorded two-expiry chain. |
| `dispersion_trade` | Two underlyings. No recorded pair of chains. |
| `no_trade_insufficient_conviction`, `no_trade_wait_iv_crush` | Advisory label. No legs and no payoff. |

Extra labels, not part of the 100:

- **Gamma Trampoline™** — incomplete for the same reason as `apex_strategy`. Change 11 published one European Black-Scholes table (spot 100, strikes 94 and 106, debit about 0.617). That is one model run, not five recorded chains. The wording was not renamed.
- **Rule 2 sell** — not a separate chain. `short_iron_condor`, `bull_put_spread_credit`, and `bear_call_spread_credit` each have five stated-premium scenarios. No recorded chain names Rule 2 as the scan winner.
- **Rule 1 buy** — covered by the five long-call identities on `apex_benchmark_greeks_strategy`.

Each stated-premium row carries `source`, `feed` (`none`), `function`, and the strikes and premiums. `evidence_ledger.py` does not exist on this branch, so those rows are not persisted there.

## Tests

Command, from `backend/`:

`backend/.venv/bin/python -m pytest -q --tb=line`

(The venv used is the origin repo venv. This worktree has no copy.)

Result: **1618 passed, 59 skipped, 0 failed**. Baseline on this commit's parent was 1530 passed, 59 skipped. The added passes are the field-removal and label checks plus 83 scenario tests and the incomplete-strategy report tests.

## Requests for other owners

- **2A.** Read `dte_min`, `dte_max`, `dte_window`, `vega_sign`, `theta_sign`, and `gamma_sign` from the knowledge entry. Enforce a DTE window only when both bounds are set. Do not invent a window where they are null. The 5-to-10-day window belongs to `gamma_trampoline` only. `double_calendar` and `apex_strategy` do not carry it. Keep the Change 11 v2 paragraphs. `resolve_strategy_id("Gamma Trampoline™")` still returns `apex_strategy` for the four-leg order template. `entry_for("Gamma Trampoline™")` returns the trademark row.
- **2B.** Persist the golden `source` / `feed` / `function` / premium inputs in the evidence ledger when that module exists. Do not describe stated premiums as a feed quote. Scan-winner assertions for these scenarios are not written here; there is no recorded chain to rank.
