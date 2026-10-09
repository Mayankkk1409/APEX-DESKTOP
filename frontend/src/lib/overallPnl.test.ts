import { describe, expect, it } from "vitest";
import {
  displayedOverallTotal,
  overallPnlCents,
  overallPnlFromCapitalFlows,
  overallTotalPnl,
  positionUnrealizedCents,
  toCents,
} from "./overallPnl";

describe("overallTotalPnl", () => {
  it("sums an all-wins book in cents", () => {
    // 250.00 + 125.50 = 375.50 → 37550 cents
    const rows = [{ realized: 250, unrealized: 0 }, { realized: 0, unrealized: 125.5 }];
    expect(overallPnlCents(rows)).toBe(37550);
    expect(overallTotalPnl(rows)).toBe(375.5);
  });

  it("reduces the total for an all-losses book", () => {
    // −80.25 + −19.75 = −100.00
    const rows = [{ realized: -80.25, unrealized: 0 }, { realized: 0, unrealized: -19.75 }];
    expect(overallPnlCents(rows)).toBe(-10000);
    expect(overallTotalPnl(rows)).toBe(-100);
  });

  it("nets a mixed book", () => {
    // +40.10 − 15.40 − 10.00 = 14.70
    const rows = [
      { realized: 40.1, unrealized: 0 },
      { realized: 0, unrealized: -15.4 },
      { realized: -10, unrealized: 0 },
    ];
    expect(overallPnlCents(rows)).toBe(1470);
    expect(overallTotalPnl(rows)).toBe(14.7);
  });

  it("keeps the short-option sign: a lower mark on a short is a gain", () => {
    // Short 2 contracts, sold at 1.50, mark 1.10, multiplier 100.
    // (1.10 − 1.50) × (−2) × 100 = +80.00 → 8000 cents
    const shortCents = positionUnrealizedCents(1.1, 1.5, -2, 100);
    // Long 1 contract, bought at 3.25, mark 2.00, multiplier 100.
    // (2.00 − 3.25) × 1 × 100 = −125.00 → −12500 cents
    const longCents = positionUnrealizedCents(2, 3.25, 1, 100);
    expect(shortCents).toBe(8000);
    expect(longCents).toBe(-12500);
    const rows = [
      { realized: 0, unrealized: shortCents / 100 },
      { realized: 0, unrealized: longCents / 100 },
    ];
    expect(overallPnlCents(rows)).toBe(-4500);
    expect(overallTotalPnl(rows)).toBe(-45);
  });

  it("subtracts fees only when a row reports them", () => {
    // 100.00 + 25.00 − 6.95 = 118.05
    const withFees = [{ realized: 100, unrealized: 25, fees: 6.95 }];
    expect(overallPnlCents(withFees)).toBe(11805);
    expect(overallTotalPnl(withFees)).toBe(118.05);
    expect(overallPnlCents([{ realized: 100, unrealized: 25 }])).toBe(12500);
  });

  it("returns zero for an empty book", () => {
    expect(overallPnlCents([])).toBe(0);
    expect(overallTotalPnl([])).toBe(0);
  });

  it("matches portfolio value minus starting capital and recorded cash flows", () => {
    // Rows: +300.00 realized − 50.00 unrealized − 0 fees = 250.00
    const rows = [{ realized: 300, unrealized: -50 }];
    expect(overallTotalPnl(rows)).toBe(250);
    // Start 10,000, deposit 500, withdraw 100, P&L 250 → equity 10,650
    // 10650 − (10000 + 500 − 100) = 250
    expect(
      overallPnlFromCapitalFlows({
        portfolioValue: 10650,
        startingCapital: 10000,
        deposits: 500,
        withdrawals: 100,
      }),
    ).toBe(overallTotalPnl(rows));
  });

  it("maps API rows through the same total Settings and Portfolio display", () => {
    const books = {
      none: [] as const,
      winningClosed: [{ realized_pl: 250, unrealized_pl: 0, qty: 0 }],
      losingOpen: [{ realized_pl: 0, unrealized_pl: -19.75, qty: 10 }],
      mixed: [
        { realized_pl: 40.1, unrealized_pl: 0 },
        { realized_pl: 0, unrealized_pl: -15.4 },
        { realized_pl: -10, unrealized_pl: 0 },
      ],
      shortOption: [
        {
          qty: -2,
          realized_pl: 0,
          unrealized_pl: positionUnrealizedCents(1.1, 1.5, -2, 100) / 100,
        },
      ],
      withFees: [{ realized_pl: 100, unrealized_pl: 25, fees: 6.95 }],
    };

    expect(displayedOverallTotal(books.none)).toBe(0);
    expect(displayedOverallTotal(books.winningClosed)).toBe(250);
    expect(displayedOverallTotal(books.losingOpen)).toBe(-19.75);
    expect(displayedOverallTotal(books.mixed)).toBe(14.7);
    expect(books.shortOption[0].qty).toBeLessThan(0);
    expect(displayedOverallTotal(books.shortOption)).toBe(80);
    expect(displayedOverallTotal(books.withFees)).toBe(118.05);

    for (const rows of Object.values(books)) {
      expect(displayedOverallTotal(rows)).toBe(
        overallTotalPnl(
          rows.map((row) => ({
            realized: "realized_pl" in row ? row.realized_pl : undefined,
            unrealized: "unrealized_pl" in row ? row.unrealized_pl : undefined,
            fees: "fees" in row ? row.fees : undefined,
          })),
        ),
      );
    }
  });

  it("rounds half-cent dollar inputs away from zero before adding", () => {
    expect(toCents(1.005)).toBe(101);
    expect(toCents(-1.005)).toBe(-101);
    expect(toCents(0.1) + toCents(0.2)).toBe(30);
    expect(overallTotalPnl([{ realized: 0.1, unrealized: 0.2 }])).toBe(0.3);
  });
});
