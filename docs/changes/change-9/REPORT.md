# Change 9 Part A — Settings and Portfolio total P&L

Part A only. Strategy scenarios (Part B) and anything after that were not started.

## Brainstorm

The two labels can disagree for a few different reasons:

1. Settings might be showing day P&L while Portfolio shows lifetime P&L.
2. Settings might be equity minus starting capital, while Portfolio sums realized and unrealized P&L.
3. The two screens might be reading different accounts (paper versus a connected brokerage).
4. The same dollars might be rounded differently, so they miss by a cent.
5. One screen might paint a fallback before its query returns.

The fix has to delete the extra formula, keep one account, and make both labels render the number Portfolio already calls overall P&L.

## Research

### Portfolio

`Portfolio` in `frontend/src/pages/Portfolio.tsx` did not subtract starting capital.

For the paper account it loaded `GET /api/portfolio/overall-pnl` (`api.overallPnl`, query key `["overall-pnl"]`). That route is `portfolio_overall_pnl` in `backend/app/routers/portfolio.py`. It calls `symbol_pnl_rows` in `backend/app/services/portfolio_pnl.py` for the signed-in user (`current_user`).

Each row has `realized_pl` and `unrealized_pl`. There is no fee column on paper orders, so `fees` is absent unless a row already carries one. `Portfolio` passed those fields to `overallTotalPnl` in `frontend/src/lib/overallPnl.ts`:

```
overall_cents = Σ realized_cents + Σ unrealized_cents − Σ fee_cents
```

Cents are half away from zero. A missing fee is left out. The same number was passed to the chart footer and the Overall P&L section (`OverallPnlTotal`).

`symbol_pnl_rows` marks an open lot as `(mark − average) × qty × multiplier`. `qty` is negative for a short, so a lower mark is a gain. Closed P&L comes from `replay_filled_orders`.

On a connected brokerage view, `Portfolio` did not call that endpoint. `brokerageOverallRows` summed open `unrealized_pl` only and forced realized P&L to 0.

### Settings

`Settings` in `frontend/src/pages/Settings.tsx` built a different number in the component body:

```
starting = portfolio.starting_balance ?? user.starting_balance ?? equity
totalPl = equity - (starting || equity)
```

`equity` was `portfolio_value` from `GET /api/portfolio` (`portfolio` in `backend/app/routers/portfolio.py`: cash plus each position's market value). On a brokerage view the portfolio query was disabled, so equity was the connected account's `total_equity`, and starting capital fell back to the paper user's `starting_balance` or to that equity.

`starting || equity` treats `0` as missing and substitutes equity, which forces the displayed total to 0.

That expression is equity minus starting capital. It is not `day_pl`. The portfolio payload's `day_pl` is the sum of open unrealized P&L inside `portfolio()`, and Settings never rendered it. Cash, buying power, and equity on the Settings account card are separate fields and stayed labeled as such.

### Why the labels diverged

Same paper account, equity `$100,000`, starting capital `$25,000`:

| Book | Settings (`equity − starting`) | Portfolio (`overallTotalPnl`) |
|---|---|---|
| No trades | +$75,000 | $0 |
| Closed winner `+$250`, equity unchanged | +$75,000 | +$250 |
| Open loser `−$19.75` | +$75,000 | −$19.75 |

They match only when equity happens to equal starting capital plus realized and unrealized P&L, with no fees and no cash move that is not a fill. A paper balance edit, a missing or zero starting balance, or the brokerage fallback breaks that. Change 3 already refused to treat equity minus starting capital as overall P&L, because deposits and withdrawals are not stored.

## Checklist

- [x] Trace both UI values to their sources and name the functions.
- [x] Both screens use `displayedOverallTotal` → `overallTotalPnl` (realized + unrealized, fees only when present, integer cents).
- [x] Delete the Settings equity-minus-starting formula.
- [x] Keep the Total P&L label, and feed it the shared overall total. Equity stays labeled Equity.
- [x] Paper view is the signed-in user from `portfolio_overall_pnl`.
- [x] Tests: no trades, winning closed trade, losing open position, mixed, short option with negative quantity. Both rendered totals equal `displayedOverallTotal`.
- [x] Do not invent deposits. State the Change 3 gap.
- [x] Do not change strategy ranking, NO TRADE behavior, or news.

## Execution

`displayedOverallTotal` in `frontend/src/lib/overallPnl.ts` maps `realized_pl`, `unrealized_pl`, and `fees` into `overallTotalPnl`.

`useAccountOverallPnl` in `frontend/src/hooks/useAccountOverallPnl.ts` is the only loader:

- Paper view: query `["overall-pnl"]`, `GET /api/portfolio/overall-pnl`, signed-in user.
- Brokerage view: `openPositionPnlRows` (open unrealized P&L, realized 0, no invented fees), then the same function.

`Settings` and `Portfolio` both read `accountPnl.total` and format it with `fmtMoney`. The chart footer and the Overall P&L section still receive that one value. Resetting the paper balance invalidates `["overall-pnl"]` along with the portfolio queries.

The equity-minus-starting line in `Settings` is gone. `overallPnlFromCapitalFlows` remains available for a book that already has deposits and withdrawals. Neither screen calls it.

## Tests

```bash
cd frontend && ./node_modules/.bin/vitest run \
  src/lib/overallPnl.test.ts \
  src/pages/totalPnlMatch.test.tsx \
  src/pages/Settings.test.tsx \
  src/pages/Portfolio.brokerage.test.tsx \
  src/components/OverallPnlTotal.test.tsx \
  src/components/PnlChart.test.tsx
```

Result: 6 files, 27 tests passed.

`totalPnlMatch.test.tsx` renders Settings and Portfolio on one query cache. Equity is `$100,000` and starting capital is `$25,000`, so the deleted formula would show `+$75,000`. Both screens instead show `fmtMoney(displayedOverallTotal(rows))`:

| Book | Shared total |
|---|---|
| No trades | $0 |
| Winning closed trade, realized $250 | +$250 |
| Losing open position, unrealized −$19.75 | −$19.75 |
| Mixed, $40.10 − $15.40 − $10.00 | +$14.70 |
| Short option, qty −2, mark $1.10 vs sale $1.50, multiplier 100 | +$80.00 |

`overallPnl.test.ts` checks those books, plus fees `$6.95` (total `$118.05`), and checks that `displayedOverallTotal` equals `overallTotalPnl` on the same rows. The brokerage portfolio test still expects `+$60` from the open position, which is that same function.

This session had no browser runner. The two screens were compared from static renders of the same cache, not by clicking Settings and Portfolio in a live window.

## Limitations

Deposits and withdrawals are not stored on the paper account. The Change 3 identity

```
overall = portfolio value − (starting capital + deposits − withdrawals)
```

cannot be enforced. Neither screen invents those cash flows, and neither uses equity minus starting capital. A paper balance edit can move equity without changing realized plus unrealized P&L. The two Total P&L labels still match, because both are that trade total.

Paper orders have no fee column. `fees` is subtracted only when a row includes it.

On a connected brokerage view, both screens sum open unrealized P&L for that connection. Closed brokerage trades and fees are not in that payload, same as before Part A. The paper total remains `GET /api/portfolio/overall-pnl` for the signed-in user whenever the view is the paper account.

## Part B — Strategy coverage

Part B only. Part C follows.

The registry has 98 real strategies with legs, plus two advisory NO TRADE stand-ins. The §9.1 matrix scores a short playbook. A 188-scenario fixture (outlook × IV versus HV × DTE bucket × risk profile, plus eight rows that turn on Δ/Θ, sentiment, or APEX Strategy eligibility) produced 12 distinct Best Match names. Every label was a real defined-risk strategy. Details, the names that never rank first, and why, are in `docs/changes/change-9/strategy-coverage.md`.

Numeric DTE does not rotate the winner. Only whether a later expiration exists does, and that only brings in calendars and diagonals.

One defect: `build_strategy_layer` relabeled Married Put as Long Put and APEX Benchmark Greeks Strategy as Long Call, because those pairs share a one-leg shape. The matrix name is kept. Weights were not changed.

Live `POST /scan` against `127.0.0.1:8000` (Alpaca) completed 34 scans across SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, and AMD. Each evaluated 98 strategies. None returned NO TRADE. JPM, XOM, KO, and WMT were not reached: the volume filled while results were being saved. The scan rows from this pass were deleted. `backend/apex.db` stays about 191MB until `VACUUM` has room to rewrite it.

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_strategy_coverage.py -q --tb=line -p no:cacheprovider
```

192 passed.

## Part C — Shared money and score sources

Part C only. Strategy ranking was not changed. Screens were not clicked. Totals were compared from static renders and unit tests of the same cache.

**Settings total P&L = Portfolio total P&L: pass.**

Both labels read `useAccountOverallPnl().total`. That hook calls `displayedOverallTotal` → `overallTotalPnl` (realized + unrealized, fees only when the row includes them, integer cents) and `fmtMoney`. Paper uses `GET /api/portfolio/overall-pnl`. A connected brokerage view sums that account's open unrealized P&L with the same function. `overallPnlFromCapitalFlows` is not called by either screen.

Grep of `frontend/src/pages/Settings.tsx`: no equity-minus-starting expression. `starting_balance` appears only in the paper-balance reset copy and the reset request body. The Total P&L node is `fmtMoney(accountPnl.total)`.

### Portfolio chart vs header

**Pass.** No code change.

`Portfolio` passes `headlineEquity` from the same `headerBalance` the page header formats with `fmtBalance` (`portfolio_value` on paper, brokerage `total_equity` when that view is on). `buildEquitySeries` keeps each observation and, when at least one bar exists, sets the last bar's value to that equity. The chart figure (`pnl-chart-value`) is that last bar. With no bars it shows the headline equity, and it does not fall through to starting capital while the headline is a finite number.

Checked with history of `$90,000` then `$91,000` and a header of `$100,000`. The header and the chart figure both rendered `$100,000`. The page did not show `$91,000`. `pnlSeries.test.ts` checks that earlier bars keep their own equity and only the last bar is replaced.

### Displayed numbers

| Screen | Label | Source | Result |
|---|---|---|---|
| Settings | Total P&L (`settings-pnl`) | `useAccountOverallPnl` → `displayedOverallTotal` | Pass |
| Portfolio | Overall total P&L (chart footer and Overall P&L footer) | Same `accountPnl.total` | Pass |
| Portfolio | Header portfolio value / equity | `portfolio_value` or brokerage `total_equity`, `fmtBalance` | Pass |
| Portfolio | Chart figure (`pnl-chart-value`) | Last `buildEquitySeries` bar, pinned to that header value | Pass |
| Settings | Cash, buying power, equity | Portfolio payload or brokerage stats. Equity is not subtracted from starting capital | Pass |
| Dashboard | Balance, buying power, portfolio value | Same portfolio or brokerage fields, plus a live fill overlay on the dashboard only | Pass |
| Dashboard | Day P&L | `day_pl` or brokerage `day_pnl`. Separate from overall P&L | Pass |
| Dashboard and Portfolio | Position unrealized P&L and market value | Position row fields | Pass |
| Dashboard | Position daily P/L | `resolvePositionDayPl` | Pass |
| Position certificate | Current P&L | That position's `unrealized_pl` | Pass |
| Position certificate | Entry score | `entry_composite_score` from the scan stored on the position, `formatCompositeScore` | Pass |
| Deep Scan | Composite gauge | `apex_score.composite_score` | Pass |
| Deep Scan | Strategy subtitle score | Strategy layer `composite_score`, restored to that same composite | Pass |
| Deep Scan | Risk-review score line | Top-level `scan.composite_score`, which the scan route copies from the apex-score layer | Pass |
| Deep Scan | Options execution score | Chain `execution_score`, set from that composite | Pass |
| Deep Scan | Pillar scores | Section scores inside the apex-score breakdown. They are inputs, not a second composite | Pass |
| Deep Scan | Sentiment gauge | Sentiment layer score. Not the composite | Pass |
| Deep Scan | Payoff (net, max loss, max profit, breakevens, leg mids) | Strategy metrics for the selected structure | Pass |
| Settings | Auto-execution minimum | Saved `autoExecMinScore`. A user gate, not the scan composite | Pass |
| Signup | Starting balance choices | Signup input. Not an account P&L | Pass |
| Brokerage panel | Paper chip | `user.portfolio_value`, whole dollars | Pass |

The composite is one number. The gauge prints one decimal, the strategy line uses `formatCompositeScore` (`72.4 / 100`), and the risk-review sentence uses `formatGateScore` (drops a trailing `.0`). Those are formatters on the same score.

Per-row Total in the Overall P&L table is the API `total_pl` (realized + unrealized). The labeled overall total uses `displayedOverallTotal`, which also subtracts `fees` when a row has them. Paper rows do not carry fees, so the labeled totals match the row sum. Neither label uses equity minus starting capital.

Dashboard account stats can move from the fill websocket before Settings and Portfolio refetch `GET /api/portfolio`. That overlay is the same balance fields, not a second total-P&L formula.

### Tests

```bash
cd frontend && ./node_modules/.bin/vitest run \
  src/lib/overallPnl.test.ts \
  src/pages/totalPnlMatch.test.tsx \
  src/pages/Settings.test.tsx \
  src/pages/Portfolio.brokerage.test.tsx \
  src/components/OverallPnlTotal.test.tsx \
  src/components/PnlChart.test.tsx \
  src/lib/pnlSeries.test.ts
```

Result: 7 files, 34 tests passed.

`totalPnlMatch.test.tsx` renders Settings and Portfolio on one cache. Equity `$100,000`, starting capital `$25,000`. The deleted formula would show `+$75,000`. Both labels show `fmtMoney(displayedOverallTotal(rows))`:

| Book | Shared total |
|---|---|
| Empty (no trades) | $0 |
| Winning closed trade, realized $250 | +$250 |
| Losing open position, unrealized −$19.75 | −$19.75 |
| Mixed | +$14.70 |
| Short option | +$80.00 |

The new case in that file checks the chart figure against the header when history ends at `$91,000`.

Not clicked: Dashboard, Settings, Portfolio, Deep Scan, and the position certificate were not opened in a browser. No lifecycle run.
