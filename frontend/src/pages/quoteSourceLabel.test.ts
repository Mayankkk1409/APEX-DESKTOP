import { describe, expect, it } from "vitest";
import { quoteSourceLabel } from "./Dashboard";

describe("quoteSourceLabel", () => {
  it("keeps indicative, opra, and demo visible", () => {
    expect(quoteSourceLabel("indicative", "opra")).toContain("indicative");
    expect(quoteSourceLabel("indicative", "opra")).toContain("opra");
    expect(quoteSourceLabel("demo", null)).toContain("demo");
  });
});
