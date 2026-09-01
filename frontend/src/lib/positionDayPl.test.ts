import { describe, expect, it } from "vitest";
import { extractBrokerageDayPl, resolvePositionDayPl } from "./positionDayPl";

describe("positionDayPl", () => {
  it("extracts vendor day P&L from brokerage position fields", () => {
    expect(
      extractBrokerageDayPl({
        symbol: "AAPL",
        quantity: 1,
        average_cost: 100,
        current_price: 110,
        market_value: 110,
        unrealized_pnl: 10,
        currency: "USD",
        day_pnl: 4.5,
      }),
    ).toBe(4.5);
  });

  it("prefers stored day_pl on PositionRow", () => {
    expect(resolvePositionDayPl({ qty: 2, day_pl: 12 }, { change: 1 })).toBe(12);
  });

  it("computes day P&L from quote change when vendor value is missing", () => {
    expect(resolvePositionDayPl({ qty: 3, day_pl: null }, { change: 2.5 })).toBe(7.5);
  });

  it("returns null when neither vendor nor quote data is available", () => {
    expect(resolvePositionDayPl({ qty: 1, day_pl: null }, null)).toBeNull();
  });
});
