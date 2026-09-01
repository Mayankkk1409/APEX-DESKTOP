import { describe, expect, it } from "vitest";
import { SCAN_SLIDE_LAYERS } from "./constants";

describe("SCAN_SLIDE_LAYERS", () => {
  it("places apex_score before strategy and risk_review last", () => {
    expect(SCAN_SLIDE_LAYERS).toEqual([
      "technical",
      "options_chain_greeks",
      "volatility",
      "sentiment",
      "fundamentals",
      "apex_score",
      "strategy",
      "risk_review",
    ]);
    expect(SCAN_SLIDE_LAYERS.length).toBe(8);
  });
});
