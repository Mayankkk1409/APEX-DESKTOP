import { describe, expect, it } from "vitest";
import { formatBreakevens, formatStrategyPremium } from "./strategyFormat";

describe("strategyFormat", () => {
  it("formats breakevens with strike precision", () => {
    expect(formatBreakevens([102.5, 108])).toBe("102.50 · 108.00");
    expect(formatBreakevens([])).toBe("—");
  });

  it("labels net debit and credit", () => {
    expect(formatStrategyPremium(2.15, "debit")).toBe("$2.15 debit");
    expect(formatStrategyPremium(1.8, "credit")).toBe("$1.80 credit");
    expect(formatStrategyPremium(null, null)).toBe("—");
  });
});
