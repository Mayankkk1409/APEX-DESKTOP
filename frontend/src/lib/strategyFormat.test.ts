import { describe, expect, it } from "vitest";
import { breakevenIvAssumptionNote, formatBreakevens, formatStrategyPremium } from "./strategyFormat";

describe("strategyFormat", () => {
  it("formats breakevens with strike precision", () => {
    expect(formatBreakevens([102.5, 108])).toBe("102.50 · 108.00");
    expect(formatBreakevens([])).toBe("—");
  });

  it("formats breakeven range for calendar spreads", () => {
    expect(formatBreakevens([{ type: "range", lower: 315.2, upper: 324.8 }])).toBe("315.20 – 324.80");
    expect(formatBreakevens([101.2, { type: "range", lower: 310, upper: 320 }])).toBe(
      "101.20 · 310.00 – 320.00",
    );
  });

  it("surfaces IV assumption note from metrics or range payload", () => {
    expect(
      breakevenIvAssumptionNote([{ type: "range", lower: 1, upper: 2, iv_assumption: true }], {}),
    ).toContain("implied volatility");
    expect(
      breakevenIvAssumptionNote([], { breakeven_iv_assumption: true }),
    ).toContain("implied volatility");
    expect(
      breakevenIvAssumptionNote([], { breakeven_assumption_note: "Custom IV note." }),
    ).toBe("Custom IV note.");
    expect(breakevenIvAssumptionNote([102.5], {})).toBeNull();
  });

  it("labels net debit and credit", () => {
    expect(formatStrategyPremium(2.15, "debit")).toBe("$2.15 debit");
    expect(formatStrategyPremium(1.8, "credit")).toBe("$1.80 credit");
    expect(formatStrategyPremium(null, null)).toBe("—");
  });
});
