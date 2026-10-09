# Final regression — seven parallel changes

Checked behaviors still hold. This pass did not edit application source and did not commit.

## What changed

1. News empty state is a live per-symbol Alpaca query: "No recent news for {SYMBOL} from Alpaca News."
2. Brokerage filler is gone: "Paper account is always available" and "Connect via SnapTrade for live read-only account data."
3. Portfolio overall P&L is one shared cent-based total (`overallTotalPnl`); the chart engine stays `apex-equity`.
4. A score under the saved auto-exec minimum still shows the strategy and Place Trade. "BELOW EXECUTION THRESHOLD" and "Below execution threshold" are absent. New accounts default the minimum to 85.
5. Scan payloads include `strategies_evaluated`. Best Match is one label. Debit-vertical max loss is net debit × multiplier.
6. Expiry notice lists paper positions inside seven days and can close them; `expiry_close` does not submit SnapTrade / `real_brokerage` accounts.
7. The registry walk records every strategy evaluated and still returns a single Best Match.

## Behaviors confirmed

- Empty news copy is the Alpaca sentence. The forbidden stored-headlines sentence is not in app source.
- The two brokerage filler sentences are not in app source.
- Portfolio uses `overallTotalPnl` for the shared total. `PnlChart` is marked `data-chart-engine="apex-equity"`.
- Placement below the saved minimum keeps the structure and an enabled Place Trade. The new-account default is 85.
- `strategies_evaluated` is on the strategy layer. Debit vertical max loss uses net debit × the contract multiplier.
- `test_expiry_close.py` includes `test_read_only_account_is_not_submitted`. Auto-close loads only `paper_funded` users.

## Tests run

Backend (`backend/.venv`, pytest), 103 passed, 0 failed:

| File | Passed |
| --- | ---: |
| `tests/test_news_authenticity.py` | 16 |
| `tests/test_auto_execution_threshold.py` | 12 |
| `tests/test_strategy_engine.py` | 37 |
| `tests/test_structure_payoff.py` | 6 |
| `tests/test_expiry_close.py` | 7 |
| `tests/test_portfolio.py` | 8 |
| `tests/test_apex_upgrade.py` | 17 |

Frontend (Vitest 2.1.9), 9 files, 54 passed, 0 failed:

| File | Passed |
| --- | ---: |
| `src/components/BrokerageConnectionPanel.test.tsx` | 7 |
| `src/lib/overallPnl.test.ts` | 8 |
| `src/components/OverallPnlTotal.test.tsx` | 4 |
| `src/components/PnlChart.test.tsx` | 6 |
| `src/lib/riskReview.test.ts` | 9 |
| `src/lib/userSettings.test.ts` | 6 |
| `src/components/scanSlides.test.tsx` | 7 |
| `src/lib/expiryNotice.test.ts` | 4 |
| `src/components/OrderConfirmationCertificate.test.tsx` | 3 |

## Defects fixed in this pass

None. The suites passed on the first run. No import clash or overlapping edit needed a repair.

## Limitations

- Deposits and withdrawals are not tracked. Overall P&L is realized plus unrealized minus reported fees. The screen does not invent cash flows, and it does not treat equity minus starting capital as the total.
- Many strategy types have no closed-form payoff in `structure_math.py`. Documented forms cover debit and credit verticals, short and long iron condors, and long calls and puts. Other registry names keep their existing handlers.
- No new paid data vendors. Headlines stay on Alpaca News.
