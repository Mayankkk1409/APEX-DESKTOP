import { describe, expect, it } from "vitest";
import { topMoverSymbols } from "./topMovers";

describe("topMoverSymbols", () => {
  it("ranks the active book by absolute open P&L and keeps five names", () => {
    expect(
      topMoverSymbols([
        { symbol: "INTC261016C00121000", unrealized_pl: 40 },
        { symbol: "TSLA", unrealized_pl: -900 },
        { symbol: "NVDA", unrealized_pl: 120 },
        { symbol: "AMD", unrealized_pl: 10 },
        { symbol: "AAPL", unrealized_pl: -50 },
        { symbol: "MSFT", unrealized_pl: 5 },
      ]),
    ).toEqual(["TSLA", "NVDA", "AAPL", "INTC261016C00121000", "AMD"]);
  });

  it("returns an empty list when the viewed account has no positions", () => {
    expect(topMoverSymbols([])).toEqual([]);
  });
});
