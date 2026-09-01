import { describe, expect, it } from "vitest";
import { formatCompositeScore } from "./scoreFormat";

describe("formatCompositeScore", () => {
  it("formats finite scores as X / 100", () => {
    expect(formatCompositeScore(72.4)).toBe("72.4 / 100");
    expect(formatCompositeScore(100)).toBe("100.0 / 100");
  });

  it("returns em dash for missing values", () => {
    expect(formatCompositeScore(null)).toBe("—");
    expect(formatCompositeScore(undefined)).toBe("—");
    expect(formatCompositeScore(Number.NaN)).toBe("—");
  });
});
