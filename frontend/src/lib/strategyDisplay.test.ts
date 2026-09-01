import { describe, expect, it } from "vitest";
import { insufficientConvictionLabel, isInsufficientConviction, normalizeStrategyName } from "./strategyDisplay";

describe("strategyDisplay", () => {
  it("renames Gamma Trampoline to APEX Strategy", () => {
    expect(normalizeStrategyName("Gamma Trampoline™")).toBe("APEX Strategy");
    expect(normalizeStrategyName("GAMMA TRAMPOLINE")).toBe("APEX Strategy");
    expect(normalizeStrategyName("Bull Call Spread")).toBe("Bull Call Spread");
  });

  it("flags insufficient conviction below floor", () => {
    expect(isInsufficientConviction(49)).toBe(true);
    expect(isInsufficientConviction(50)).toBe(false);
    expect(isInsufficientConviction(null)).toBe(true);
  });

  it("uses canonical no-trade label", () => {
    expect(insufficientConvictionLabel()).toBe("No Trade / Insufficient Conviction");
  });
});
