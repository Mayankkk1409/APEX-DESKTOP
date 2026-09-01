import { describe, expect, it } from "vitest";
import { assetLabel, fmtMoney, fmtTs } from "./portfolioFormat";

describe("portfolioFormat", () => {
  it("formats signed money", () => {
    expect(fmtMoney(1234.5)).toBe("+$1,234.5");
    expect(fmtMoney(-50)).toBe("-$50");
    expect(fmtMoney(0)).toBe("$0");
  });

  it("labels asset class", () => {
    expect(assetLabel("us_option")).toBe("Option");
    expect(assetLabel("us_equity")).toBe("Equity");
  });

  it("formats timestamps", () => {
    expect(fmtTs(null)).toBe("—");
    expect(fmtTs("2026-01-15T18:30:00.000Z")).toMatch(/Jan/);
  });
});
