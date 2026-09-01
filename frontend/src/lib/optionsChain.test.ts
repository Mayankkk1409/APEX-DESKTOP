import { describe, expect, it } from "vitest";
import {
  atmStrike,
  buildLadder,
  chainWideFlagNotes,
  chainWideFlags,
  expiryMatches,
  greekProvenanceIsMixed,
  flagLabels,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtSigned,
  gateSummary,
  hasRenderableChain,
  midOf,
  moneyness,
  spreadPctOfMid,
  VERDICT_LABELS,
} from "./optionsChain";
import type { ChainAnalysis, ChainContractRow, ContractVerdict, Gate } from "../types";

function gate(id: string, status: Gate["status"], observed = "obs"): Gate {
  return { id, label: `${id} gate`, status, rule: "rule", observed, detail: "detail" };
}

function verdict(over: Partial<ContractVerdict> = {}): ContractVerdict {
  return {
    symbol: "XYZ260701C00100000",
    strike: 100,
    side: "call",
    verdict: "tradeable",
    hard_reject: false,
    moneyness: "atm",
    dte: 30,
    mid: 2,
    spread_abs: 0.1,
    spread_pct_of_mid: 0.05,
    delta_theta_ratio: 12,
    theta_pct_of_mid: 0.02,
    vega_pct_of_mid: 0.045,
    gamma_delta_shift_1pct: 0.02,
    volume_oi_ratio: 0.4,
    itm_probability_proxy: 0.55,
    breakeven: 102,
    buy_score: 71,
    sell_score: 22,
    gates: [],
    flags: [],
    reasons: [],
    reasoning: "reasoning",
    greeks_source: "vendor",
    ...over,
  };
}

function row(strike: number, side: "call" | "put", over: Partial<ChainContractRow> = {}): ChainContractRow {
  return {
    symbol: `XYZ260701${side[0].toUpperCase()}${strike}`,
    strike,
    side,
    bid: 1.95,
    ask: 2.05,
    bid_size: 10,
    ask_size: 12,
    last: 2,
    prev_close: 1.9,
    change: 0.1,
    change_pct: 0.0526,
    volume: 800,
    open_interest: 2000,
    iv: 0.32,
    delta: side === "call" ? 0.55 : -0.45,
    gamma: 0.02,
    theta: -0.04,
    vega: 0.09,
    rho: 0.01,
    greeks_source: "vendor",
    iv_source: "vendor",
    quote_as_of: null,
    verdict: verdict({ strike, side }),
    ...over,
  };
}

describe("formatting", () => {
  it("renders a missing datum as an em dash rather than a zero", () => {
    for (const bad of [null, undefined, NaN, Infinity]) {
      expect(fmtNum(bad as number | null)).toBe("—");
      expect(fmtInt(bad as number | null)).toBe("—");
      expect(fmtPct(bad as number | null)).toBe("—");
      expect(fmtSigned(bad as number | null)).toBe("—");
    }
  });

  it("keeps a real zero visible", () => {
    expect(fmtNum(0)).toBe("0.00");
    expect(fmtInt(0)).toBe("0");
    expect(fmtPct(0)).toBe("0.00%");
    expect(fmtSigned(0)).toBe("+0.00");
  });

  it("formats prices, counts, percentages and signed changes", () => {
    expect(fmtNum(1234.5678)).toBe("1,234.57");
    expect(fmtNum(0.123456, 4)).toBe("0.1235");
    expect(fmtInt(74000)).toBe("74,000");
    expect(fmtPct(0.0525)).toBe("5.25%");
    expect(fmtPct(0.1, 0)).toBe("10%");
    expect(fmtSigned(0.42)).toBe("+0.42");
    expect(fmtSigned(-0.42)).toBe("-0.42");
  });
});

describe("mid and spread", () => {
  it("computes the mid of a two-sided market", () => {
    expect(midOf(1.95, 2.05)).toBeCloseTo(2.0);
    expect(spreadPctOfMid(1.95, 2.05)).toBeCloseTo(0.05);
  });

  it("returns null when there is no market at all", () => {
    expect(midOf(0, 0)).toBeNull();
    expect(spreadPctOfMid(0, 0)).toBeNull();
  });

  it("treats a zero bid with a live ask as a real one-sided market", () => {
    expect(midOf(0, 0.05)).toBeCloseTo(0.025);
    expect(spreadPctOfMid(0, 0.05)).toBeCloseTo(2.0);
  });

  it("returns null for a missing side or a crossed market", () => {
    expect(midOf(null, 2.05)).toBeNull();
    expect(midOf(1.95, null)).toBeNull();
    expect(midOf(undefined, undefined)).toBeNull();
    expect(midOf(2.2, 2.0)).toBeNull();
    expect(spreadPctOfMid(null, 2.05)).toBeNull();
  });

  it("does not choke on non-finite quotes", () => {
    expect(midOf(NaN, 2)).toBeNull();
    expect(midOf(1, Infinity)).toBeNull();
  });
});

describe("ATM and moneyness", () => {
  it("picks the strike nearest spot", () => {
    const strikes = [90, 95, 100, 105, 110].map((strike) => ({ strike }));
    expect(atmStrike(strikes, 101)).toBe(100);
    expect(atmStrike(strikes, 103)).toBe(105);
    expect(atmStrike(strikes, 100)).toBe(100);
  });

  it("refuses to guess an ATM without a spot reference", () => {
    const strikes = [90, 100].map((strike) => ({ strike }));
    expect(atmStrike(strikes, null)).toBeNull();
    expect(atmStrike(strikes, undefined)).toBeNull();
    expect(atmStrike(strikes, 0)).toBeNull();
    expect(atmStrike(strikes, NaN)).toBeNull();
    expect(atmStrike([], 100)).toBeNull();
  });

  it("classifies calls and puts on opposite sides of spot", () => {
    expect(moneyness("call", 90, 100)).toBe("itm");
    expect(moneyness("call", 110, 100)).toBe("otm");
    expect(moneyness("put", 110, 100)).toBe("itm");
    expect(moneyness("put", 90, 100)).toBe("otm");
    expect(moneyness("call", 100, null)).toBe("unknown");
  });
});

describe("buildLadder", () => {
  it("pairs calls and puts onto one row per strike, sorted by strike", () => {
    const ladder = buildLadder(
      [row(105, "put"), row(95, "call"), row(105, "call"), row(95, "put"), row(100, "call"), row(100, "put")],
      100,
    );
    expect(ladder.map((r) => r.strike)).toEqual([95, 100, 105]);
    expect(ladder.every((r) => r.call !== null && r.put !== null)).toBe(true);
  });

  it("marks the recommended strike row when supplied by the server", () => {
    const recommended = { symbol: "XYZ", expiry: "2026-07-01", strike: 100, side: "call" as const, contract_id: "X" };
    const ladder = buildLadder([row(95, "call"), row(100, "call"), row(105, "call")], 101, recommended);
    expect(ladder.filter((r) => r.isRecommended).map((r) => r.strike)).toEqual([100]);
    expect(ladder.find((r) => r.strike === 100)?.recommendedSide).toBe("call");
  });

  it("marks no recommended row when the server did not pick one", () => {
    const ladder = buildLadder([row(95, "call"), row(100, "call")], 100, null);
    expect(ladder.some((r) => r.isRecommended)).toBe(false);
  });

  it("shades the in-the-money side of each strike", () => {
    const ladder = buildLadder([row(90, "call"), row(90, "put"), row(110, "call"), row(110, "put")], 100);
    expect(ladder.find((r) => r.strike === 90)?.itmSide).toBe("call");
    expect(ladder.find((r) => r.strike === 110)?.itmSide).toBe("put");
  });

  it("keeps a single-sided strike instead of dropping it", () => {
    const ladder = buildLadder([row(95, "call"), row(100, "put")], 100);
    expect(ladder).toHaveLength(2);
    expect(ladder[0].put).toBeNull();
    expect(ladder[1].call).toBeNull();
  });

  it("surfaces rejects, gate failures and UOA at the row level", () => {
    const ladder = buildLadder(
      [
        row(95, "call", { verdict: verdict({ verdict: "rejected", hard_reject: true }) }),
        row(100, "call", { verdict: verdict({ verdict: "screened_out" }) }),
        row(105, "call", { verdict: verdict({ flags: ["uoa"] }) }),
        row(110, "call"),
      ],
      100,
    );
    expect(ladder.find((r) => r.strike === 95)?.hasReject).toBe(true);
    expect(ladder.find((r) => r.strike === 100)?.hasGateFailure).toBe(true);
    expect(ladder.find((r) => r.strike === 105)?.hasUoa).toBe(true);
    const clean = ladder.find((r) => r.strike === 110)!;
    expect([clean.hasReject, clean.hasGateFailure, clean.hasUoa]).toEqual([false, false, false]);
  });

  it("tolerates a missing verdict and a non-finite strike", () => {
    const ladder = buildLadder([row(100, "call", { verdict: null }), row(NaN, "put")], 100);
    expect(ladder).toHaveLength(1);
    expect(ladder[0].hasReject).toBe(false);
  });

  it("returns an empty ladder for an empty chain", () => {
    expect(buildLadder([], 100)).toEqual([]);
  });
});

describe("verdict presentation", () => {
  it("labels every verdict kind", () => {
    for (const kind of [
      "buy_candidate",
      "sell_candidate",
      "tradeable",
      "screened_out",
      "rejected",
      "insufficient_data",
    ]) {
      expect(VERDICT_LABELS[kind]).toBeTruthy();
    }
  });

  it("summarises the gates that actually fired", () => {
    const text = gateSummary(
      verdict({
        verdict: "rejected",
        gates: [gate("spread", "fail", "0.90 wide on a 1.00 mid = 90.00%"), gate("uoa", "warn"), gate("delta", "unknown")],
      }),
    );
    expect(text).toContain("HARD REJECT");
    expect(text).toContain("90.00%");
    expect(text).toContain("Warn:");
    expect(text).toContain("Unknown:");
  });

  it("says so plainly when nothing was evaluated", () => {
    expect(gateSummary(null)).toBe("Not evaluated.");
  });

  it("maps flags to short badges", () => {
    expect(flagLabels(verdict({ flags: ["uoa", "rule1_buy", "gamma_risk_7dte", "vega_cap_blocked"] }))).toEqual([
      "UOA",
      "RULE 1",
      "GAMMA 7D",
      "VEGA CAP",
    ]);
    expect(flagLabels(verdict({ flags: [] }))).toEqual([]);
    expect(flagLabels(null)).toEqual([]);
  });

  it("drops flags that were hoisted to chain level", () => {
    expect(flagLabels(verdict({ flags: ["uoa", "gamma_risk_7dte"] }), ["gamma_risk_7dte"])).toEqual(["UOA"]);
  });
});

describe("chain-wide flags", () => {
  const withFlags = (strike: number, flags: string[]) => row(strike, "call", { verdict: verdict({ strike, flags }) });

  it("hoists a flag every graded contract carries", () => {
    const flags = chainWideFlags([
      withFlags(95, ["gamma_risk_7dte", "uoa"]),
      withFlags(100, ["gamma_risk_7dte"]),
      withFlags(105, ["gamma_risk_7dte"]),
    ]);
    expect(flags).toEqual(["gamma_risk_7dte"]);
    expect(chainWideFlagNotes(flags)[0]).toContain("7 days");
  });

  it("leaves a flag on the row when it singles a strike out", () => {
    expect(chainWideFlags([withFlags(95, ["uoa"]), withFlags(100, []), withFlags(105, [])])).toEqual([]);
  });

  it("ignores ungradeable contracts when deciding what is chain-wide", () => {
    const flags = chainWideFlags([
      withFlags(95, ["vega_cap_blocked"]),
      withFlags(100, ["vega_cap_blocked"]),
      row(105, "call", { verdict: verdict({ verdict: "insufficient_data", flags: [] }) }),
    ]);
    expect(flags).toEqual(["vega_cap_blocked"]);
  });

  it("hoists nothing from a chain too small to have a pattern", () => {
    expect(chainWideFlags([withFlags(100, ["uoa"])])).toEqual([]);
    expect(chainWideFlags([])).toEqual([]);
  });

  it("falls back to a generic sentence for an unrecognised flag", () => {
    expect(chainWideFlagNotes(["some_new_rule"])[0]).toContain("SOME_NEW_RULE");
  });
});

describe("greek provenance", () => {
  it("is mixed only when contracts actually disagree", () => {
    expect(greekProvenanceIsMixed([row(95, "call"), row(100, "call")])).toBe(false);
    expect(greekProvenanceIsMixed([row(95, "call"), row(100, "call", { greeks_source: "model" })])).toBe(true);
    expect(greekProvenanceIsMixed([])).toBe(false);
  });
});

describe("session guards", () => {
  it("detects when a loaded chain does not match the session expiry", () => {
    const analysis = { expiry: "2026-07-01" } as Pick<ChainAnalysis, "expiry">;
    expect(expiryMatches(analysis, "2026-07-01")).toBe(true);
    expect(expiryMatches(analysis, "2026-07-08")).toBe(false);
    expect(expiryMatches(analysis, "")).toBe(false);
    expect(expiryMatches({ expiry: null }, "2026-07-01")).toBe(false);
    expect(expiryMatches(null, "2026-07-01")).toBe(false);
  });

  it("knows when there is nothing to render a table for", () => {
    expect(hasRenderableChain(null)).toBe(false);
    expect(hasRenderableChain({ contracts: [] } as unknown as ChainAnalysis)).toBe(false);
    expect(hasRenderableChain({ contracts: [row(100, "call")] } as unknown as ChainAnalysis)).toBe(true);
  });
});
