import { describe, expect, it } from "vitest";
import { scoreTier } from "./chartHighlight";
import { buildLadder } from "./optionsChain";
import type { ChainContractRow, RecommendedContract } from "../types";

const recommended: RecommendedContract = {
  symbol: "XYZ",
  expiry: "2026-07-01",
  strike: 100,
  side: "call",
  contract_id: "XYZ260701C00100000",
};

function row(strike: number, side: "call" | "put"): ChainContractRow {
  return {
    symbol: `${side}-${strike}`,
    strike,
    side,
    bid: 1.9,
    ask: 2.1,
    bid_size: 10,
    ask_size: 10,
    last: 2,
    prev_close: 1.9,
    change: 0.1,
    change_pct: 0.05,
    volume: 500,
    open_interest: 1000,
    iv: 0.3,
    delta: 0.5,
    gamma: 0.02,
    theta: -0.04,
    vega: 0.08,
    rho: 0.01,
    greeks_source: "vendor",
    iv_source: "vendor",
    quote_as_of: null,
    verdict: null,
  };
}

describe("options chain score tier highlighting", () => {
  it("does not mark a recommended row when tier is blocked", () => {
    expect(scoreTier(45)).toBe("blocked");
    const ladder = buildLadder([row(100, "call"), row(100, "put")], 100, null);
    expect(ladder.some((r) => r.isRecommended)).toBe(false);
  });

  it("highlights the recommended leg in the caution band", () => {
    expect(scoreTier(65)).toBe("caution");
    const ladder = buildLadder([row(100, "call"), row(105, "call")], 100, recommended);
    const hit = ladder.find((r) => r.strike === 100);
    expect(hit?.isRecommended).toBe(true);
    expect(hit?.recommendedSide).toBe("call");
  });

  it("highlights the recommended leg in the auto-exec band", () => {
    expect(scoreTier(85, 85)).toBe("auto_exec");
    const ladder = buildLadder([row(100, "call"), row(105, "call")], 100, recommended);
    expect(ladder.find((r) => r.strike === 100)?.isRecommended).toBe(true);
  });
});
