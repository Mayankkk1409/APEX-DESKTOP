import { describe, expect, it } from "vitest";
import { preferredFullExpiry } from "./fullChainExpiry";

const intc = [
  { date: "2026-10-12", listed: 81 },
  { date: "2026-10-16", listed: 102 },
  { date: "2026-10-19", listed: 1 },
];

describe("preferredFullExpiry", () => {
  it("moves a one-call expiry to the nearest full chain", () => {
    expect(preferredFullExpiry(intc, "2026-10-19", null)).toBe("2026-10-12");
  });

  it("keeps a full listing", () => {
    expect(preferredFullExpiry(intc, "2026-10-16", null)).toBeNull();
  });

  it("keeps a stub the user just picked", () => {
    expect(preferredFullExpiry(intc, "2026-10-19", "2026-10-19")).toBeNull();
  });

  it("fills an empty selection with the nearest full chain", () => {
    expect(preferredFullExpiry(intc, "", null)).toBe("2026-10-12");
  });
});
