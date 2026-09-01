import { describe, expect, it } from "vitest";
import { humanizeLabel } from "./humanizeLabel";

describe("humanizeLabel", () => {
  it("title-cases snake_case enum keys", () => {
    expect(humanizeLabel("aggressive_bullish")).toBe("Aggressive Bullish");
    expect(humanizeLabel("consecutive_beats")).toBe("Consecutive Beats");
    expect(humanizeLabel("selected_expiry_session")).toBe("Selected Expiry Session");
  });

  it("splits camelCase boundaries", () => {
    expect(humanizeLabel("selectedExpirySession")).toBe("Selected Expiry Session");
  });

  it("handles empty and single words", () => {
    expect(humanizeLabel("")).toBe("");
    expect(humanizeLabel(null)).toBe("");
    expect(humanizeLabel("strong")).toBe("Strong");
  });
});
