import { describe, expect, it } from "vitest";
import { readPortfolioViewMode, writePortfolioViewMode } from "./portfolioViewMode";

describe("portfolioViewMode", () => {
  it("reads and writes the active view mode", () => {
    writePortfolioViewMode("brokerage");
    expect(readPortfolioViewMode()).toBe("brokerage");
    writePortfolioViewMode("paper");
    expect(readPortfolioViewMode()).toBe("paper");
  });
});
