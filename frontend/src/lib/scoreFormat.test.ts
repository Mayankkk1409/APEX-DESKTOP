import { describe, expect, it } from "vitest";
import { formatCompositeDecimal, formatCompositeScore } from "./scoreFormat";

describe("formatCompositeDecimal", () => {
  it("shows 59 as 59.0 and leaves 62.9 at one decimal", () => {
    expect(formatCompositeDecimal(59)).toBe("59.0");
    expect(formatCompositeDecimal(62.9)).toBe("62.9");
  });

  it("returns em dash for missing values", () => {
    expect(formatCompositeDecimal(null)).toBe("—");
    expect(formatCompositeDecimal(undefined)).toBe("—");
    expect(formatCompositeDecimal(Number.NaN)).toBe("—");
    expect(formatCompositeDecimal(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("formatCompositeScore", () => {
  it("formats finite scores as one decimal over 100", () => {
    expect(formatCompositeScore(72.4)).toBe("72.4 / 100");
    expect(formatCompositeScore(100)).toBe("100.0 / 100");
    expect(formatCompositeScore(59)).toBe("59.0 / 100");
    expect(formatCompositeScore(62.9)).toBe("62.9 / 100");
  });

  it("returns em dash for missing values", () => {
    expect(formatCompositeScore(null)).toBe("—");
    expect(formatCompositeScore(undefined)).toBe("—");
    expect(formatCompositeScore(Number.NaN)).toBe("—");
  });
});
