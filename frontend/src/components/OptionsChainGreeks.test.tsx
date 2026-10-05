import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store";
import { createTestQueryClient } from "../test/queryClient";
import type { ChainAnalysis, ChainContractRow, RecommendedContract } from "../types";
import { OptionsChainGreeks } from "./OptionsChainGreeks";

vi.mock("../api", () => ({
  api: {
    optionsAnalysis: vi.fn(async () => {
      throw new Error("standalone chain refetch must not choose the highlighted leg");
    }),
  },
}));

const EXPIRY = "2026-09-18";

function contract(strike: number, side: "call" | "put"): ChainContractRow {
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
    volume: 400,
    open_interest: 800,
    iv: 0.3,
    delta: side === "call" ? 0.5 : -0.5,
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

function analysis(symbol: string, strikes: { strike: number; side: "call" | "put" }[], score: number): ChainAnalysis {
  const atm: RecommendedContract = {
    symbol,
    expiry: EXPIRY,
    strike: 100,
    side: "call",
    contract_id: null,
  };
  return {
    title: "Chain",
    symbol,
    expiry: EXPIRY,
    expiry_valid: true,
    dte: 15,
    spot: 100,
    spot_source: "quote",
    atm_strike: 100,
    recommendedContract: atm,
    execution_score: score,
    execution_tier: score <= 50 ? "blocked" : score >= 85 ? "auto_exec" : "caution",
    data_source: {
      status: "live",
      label: "Live",
      is_live: true,
      source: "alpaca",
      feed: "opra",
      greeks_source: "vendor",
      as_of: null,
      vendor_greeks: strikes.length,
      model_greeks: 0,
      missing_greeks: 0,
      caveats: [],
    },
    thresholds: {
      buy_delta_min: 0.5,
      sell_delta_max: 0.25,
      rule1_delta_min: 0.55,
      rule1_theta_max: 0.05,
      rule2_delta_max: 0.2,
      delta_theta_buy_min: 10,
      delta_theta_sell_max: 5,
      spread_max_pct_of_mid: 0.1,
      spread_max_pct_illiquid: 0.15,
      min_open_interest: 500,
      volume_oi_min_ratio: 0.25,
      uoa_volume_multiple: 3,
      gamma_dte_flag: 7,
    },
    vega_cap: {
      catalyst_environment: false,
      reason: "",
      override_granted: false,
      structure_absorbs_gamma: false,
      blocks_long_premium: false,
    },
    contracts: strikes.map((row) => contract(row.strike, row.side)),
    summary: {
      contract_count: strikes.length,
      call_count: strikes.filter((row) => row.side === "call").length,
      put_count: strikes.filter((row) => row.side === "put").length,
      single_sided: false,
      verdict_counts: {},
      gate_failures: {},
      gate_unknown: {},
      unusual_activity: [],
      vega_cap_blocked: [],
      gamma_flagged: [],
    },
    cards: [],
    narrative: "",
  };
}

function renderChain(
  symbol: string,
  score: number,
  strategyHighlight: {
    legs?: { side?: string; option_side?: string; strike?: number; expiry?: string; symbol?: string }[] | null;
    recommended?: RecommendedContract | null;
  },
) {
  const strikes = [
    { strike: 90, side: "put" as const },
    { strike: 100, side: "call" as const },
    { strike: 100, side: "put" as const },
    { strike: 220, side: "call" as const },
    { strike: 420, side: "call" as const },
  ];
  return renderToStaticMarkup(
    <QueryClientProvider client={createTestQueryClient()}>
      <OptionsChainGreeks
        symbol={symbol}
        expiry={EXPIRY}
        initial={analysis(symbol, strikes, score)}
        executionScore={score}
        strategyHighlight={strategyHighlight}
      />
    </QueryClientProvider>,
  );
}

function rowMarked(html: string, strike: number): boolean {
  return html.includes(`data-testid="chain-row-${strike}" data-recommended="true"`);
}

describe("options chain strategy marks", () => {
  beforeEach(() => {
    useSession.setState({
      recommendedContract: {
        symbol: "AAA",
        expiry: EXPIRY,
        strike: 100,
        side: "call",
        contract_id: "AAA",
      },
    });
  });

  it("highlights No Trade legs instead of the ATM row", () => {
    const html = renderChain("BBB", 42, {
      legs: [{ side: "put", strike: 90, expiry: EXPIRY, symbol: "BBB260918P00090000" }],
      recommended: null,
    });
    expect(html).toContain('data-execution-tier="blocked"');
    expect(rowMarked(html, 90)).toBe(true);
    expect(html).toContain('data-testid="chain-row-90" data-recommended="true" data-recommended-call="false" data-recommended-put="true"');
    expect(rowMarked(html, 100)).toBe(false);
    expect(html).toContain('data-testid="chain-leg-star"');
  });

  it("highlights legs when the composite is under the auto-exec minimum", () => {
    const html = renderChain("BBB", 70, {
      legs: [
        { side: "call", strike: 100, expiry: EXPIRY },
        { side: "call", strike: 220, expiry: "2026-10-16" },
      ],
      recommended: null,
    });
    expect(html).toContain('data-execution-tier="caution"');
    expect(rowMarked(html, 100)).toBe(true);
    expect(html).toContain('data-recommended-call="true"');
    expect(rowMarked(html, 220)).toBe(false);
  });

  it("highlights the second symbol's strikes rather than the first symbol's", () => {
    const html = renderChain("MSFT", 91, {
      legs: [{ side: "call", strike: 420, expiry: EXPIRY, symbol: "MSFT260918C00420000" }],
      recommended: { symbol: "AAPL", expiry: EXPIRY, strike: 100, side: "call", contract_id: null },
    });
    expect(rowMarked(html, 420)).toBe(true);
    expect(rowMarked(html, 100)).toBe(false);
  });

  it("shows no star when legs and strikes are both missing", () => {
    const html = renderChain("BBB", 70, { legs: [], recommended: null });
    expect(html).not.toContain('data-recommended="true"');
    expect(html).not.toContain("chain-leg-star");
  });
});
