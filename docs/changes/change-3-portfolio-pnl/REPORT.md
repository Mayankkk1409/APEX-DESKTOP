# Change 3 — Portfolio value chart and overall P&L

## Formulas

Chart bar (cash + marked positions on that observation):

```
bar = portfolio_value
```

`/api/portfolio/pnl-history` emits account open, each fill, and the live mark. Broker equity history emits each stored `total_equity` snapshot. Missing timestamps are omitted. The in-app `apex-equity` series does not insert bars between them. When history exists, the last bar keeps that observation's time and takes the portfolio value shown in the header.

Overall P&L, integer cents, half away from zero:

```
overall_cents = Σ realized_cents + Σ unrealized_cents − Σ fee_cents
overall_dollars = overall_cents / 100
```

A missing fee is left out. A negative realized or unrealized amount reduces the total.

Short option mark:

```
unrealized_cents = (mark_cents − average_cents) × qty × multiplier
```

`qty` is negative for a short, so a mark below the sale price is a gain.

When starting capital, deposits, and withdrawals are all known:

```
overall_cents = portfolio_cents − (starting_cents + deposits_cents − withdrawals_cents)
```

The portfolio screen does not call that identity. It calls `overallTotalPnl` once and passes that number to the chart footer and the Overall P&L section.

## Files

- `frontend/src/lib/overallPnl.ts` — cent math and the shared total.
- `frontend/src/lib/overallPnl.test.ts` — hand-checked books.
- `frontend/src/lib/pnlSeries.ts` — plot `portfolio_value` only; pin the last bar to the header value.
- `frontend/src/lib/pnlTimeframe.ts` — drop the fallback that connected the first point to the last.
- `frontend/src/pages/Portfolio.tsx` — one `overallTotalPnl` result for the chart footer and the section footer.
- `frontend/src/types.ts` — optional `fees` on an overall row.
- `backend/app/services/portfolio_pnl.py` — observed equity points; signed unrealized P&L in `Decimal` cents.
- `frontend/src/pages/Portfolio.brokerage.test.tsx` — footer expects open unrealized P&L, not equity minus the first snapshot.
- `frontend/src/lib/pnlSeries.test.ts`, `frontend/src/lib/pnlTimeframe.test.ts`, `backend/tests/test_portfolio.py`.

Chart engine stays `apex-equity`. Portfolio page styling was not rewritten.

## Tests

Frontend (Vitest 2.1.9):

```bash
cd frontend && ./node_modules/.bin/vitest run \
  src/lib/overallPnl.test.ts \
  src/lib/pnlSeries.test.ts \
  src/lib/pnlTimeframe.test.ts \
  src/components/PnlChart.test.tsx \
  src/components/OverallPnlTotal.test.tsx \
  src/pages/Portfolio.brokerage.test.tsx
```

Result: 6 files, 30 tests passed.

Hand checks in `overallPnl.test.ts`:

| Book | Arithmetic | Cents |
|---|---|---|
| All wins | 250.00 + 125.50 | 37550 |
| All losses | −80.25 + −19.75 | −10000 |
| Mixed | 40.10 − 15.40 − 10.00 | 1470 |
| Short option | (1.10 − 1.50) × (−2) × 100 = +80.00; long (2.00 − 3.25) × 100 = −125.00 | −4500 |
| Fees | 100.00 + 25.00 − 6.95 | 11805 |
| Fees omitted | 100.00 + 25.00 | 12500 |
| Empty book | no rows | 0 |
| Capital flows | 10650 − (10000 + 500 − 100) = 250, same as 300 − 50 | 25000 |

`toCents(1.005)` is 101 and `toCents(-1.005)` is −101. `0.10 + 0.20` sums as 30 cents.

Backend:

```bash
cd backend && .venv/bin/pytest tests/test_portfolio.py -q
```

Result: 8 passed.

Short put fixture: qty −1, average 4.00, mark 3.00, multiplier 100 → unrealized +100.00. History fixture from 2026-08-01 with one fill on 2026-08-20 returns three points (open 100000, fill 100000, live cash 99000 + 10 × 110 = 100100), not a point per calendar day.

## Limitations

Deposits and withdrawals are not stored on the paper account or on brokerage balance snapshots. The screen does not invent them, and it does not treat equity minus starting capital as overall P&L. A paper balance edit or an untracked transfer can move the chart's live point without changing realized + unrealized.

Broker equity history is the stored `total_equity` series. The connected-account overall total sums open positions only. Those rows set realized P&L to 0 because the position payload has unrealized P&L and no fees. Closed brokerage trades are absent from that sum.

Paper orders have no fee column. `fees` is subtracted only when a row includes it.

Paper fill history marks the traded symbol at the fill price and leaves other lots at average cost until the live point, which uses `cash_balance` plus each position's current price. The paper fill path still opens long positions; the short-option sign applies when `qty` is negative.

The chart connects the observations it is given. A timeframe with fewer than two points inside the window also keeps the last real point at or before the window start. That point is an existing observation, not a filled-in value.
