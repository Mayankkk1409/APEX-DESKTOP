import { describe, expect, it } from "vitest";
import { bullCallSpreadMetrics } from "./strategyMetrics";

describe("strategy metrics", () => {
  it("computes bull call spread debit, max loss, and breakeven", () => {
    const metrics = bullCallSpreadMetrics(
      [
        { side: "call", strike: 100, bid: 2.0, ask: 2.2, delta: 0.55 },
        { side: "call", strike: 105, bid: 0.9, ask: 1.1, delta: 0.35 },
      ],
      { strike: 100, side: "call" },
      100,
    );
    expect(metrics.net_type).toBe("debit");
    expect(metrics.net_debit_credit).toBeGreaterThan(0);
    expect(metrics.max_loss).toBeCloseTo(metrics.net_debit_credit! * 100, 2);
    expect(metrics.max_profit).toBeGreaterThan(0);
    expect(metrics.breakevens[0]).toBeGreaterThan(100);
    expect(metrics.legs).toHaveLength(2);
  });
});
