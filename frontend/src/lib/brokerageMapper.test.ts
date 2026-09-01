import { describe, expect, it } from "vitest";
import { mapBrokeragePositions } from "./brokerageMapper";

describe("mapBrokeragePositions", () => {
  it("maps SnapTrade positions to desk PositionRow shape", () => {
    const rows = mapBrokeragePositions([
      {
        symbol: "AAPL",
        quantity: 10,
        average_cost: 150,
        current_price: 175,
        market_value: 1750,
        unrealized_pnl: 250,
        currency: "USD",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: "brokerage-AAPL-0",
      symbol: "AAPL",
      qty: 10,
      avg_cost: 150,
      current: 175,
      market_value: 1750,
      unrealized_pl: 250,
      day_pl: null,
      asset_class: "us_equity",
    });
  });

  it("maps SnapTrade day_pnl when present", () => {
    const rows = mapBrokeragePositions([
      {
        symbol: "NVDA",
        quantity: 2,
        average_cost: 800,
        current_price: 820,
        market_value: 1640,
        unrealized_pnl: 40,
        currency: "USD",
        day_pnl: 18,
      },
    ]);
    expect(rows[0].day_pl).toBe(18);
  });
});
