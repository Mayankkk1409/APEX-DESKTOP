import { describe, expect, it } from "vitest";
import { buildCertificateLegs, buildCertificateLegsFromStrategy, formatLegDetail } from "./certificateLegs";
import type { OrderLegFill } from "../types";

describe("certificateLegs", () => {
  const legs: OrderLegFill[] = [
    { id: "1", symbol: "AAPL270115C00150000", side: "buy", qty: 1, fill_price: 4.25 },
    { id: "2", symbol: "AAPL270115C00155000", side: "sell", qty: 1, fill_price: 2.1 },
  ];

  it("parses expiration on every leg", () => {
    const built = buildCertificateLegs(legs);
    expect(built).toHaveLength(2);
    for (const leg of built) {
      expect(leg.expiration).toMatch(/Jan 15, 2027/);
      expect(leg.strike).toBeGreaterThan(0);
      expect(leg.optionSide).toBe("call");
    }
  });

  it("formats leg detail with expiration", () => {
    const built = buildCertificateLegs(legs);
    const detail = formatLegDetail(built[0]);
    expect(detail).toContain("LONG");
    expect(detail).toContain("CALL");
    expect(detail).toContain("Jan 15, 2027");
  });

  it("builds strategy legs with distinct expirations", () => {
    const built = buildCertificateLegsFromStrategy([
      { action: "sell", side: "call", strike: 150, expiry: "2026-09-18", mid: 2.1 },
      { action: "buy", side: "call", strike: 150, expiry: "2026-10-16", mid: 3.4 },
    ]);
    expect(built).toHaveLength(2);
    expect(built[0].expiration).toMatch(/Sep 18, 2026/);
    expect(built[1].expiration).toMatch(/Oct 16, 2026/);
  });
});
