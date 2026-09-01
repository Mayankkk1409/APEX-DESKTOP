import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ApexScoreScan } from "./ApexScoreScan";
import { StrategyScan } from "./StrategyScan";
import type { ApexScoreLayer, StrategyLayer } from "../types";

const apexPayload: ApexScoreLayer = {
  title: "APEX Composite Score",
  composite_score: 78.5,
  threshold_full_doc: 72,
  threshold_project_apex: 85,
  weights: { technicals: 0.3, volatility: 0.25, options: 0.2, sentiment: 0.15, fundamentals: 0.1 },
  clears_threshold: true,
  narrative: "Threshold met — proceed to strategy selection.",
  paragraphs: [
    "APEX Composite Score 78.5/100 synthesizes five weighted pillars from the captured scan.",
    "Full Document §8 execution threshold is ≥ 72.",
  ],
  interpretation: "Execution permitted by score — complete risk review checkbox.",
  sections: [
    {
      id: "technicals",
      title: "Technicals",
      score: 82,
      weight: 0.3,
      weighted_contribution: 24.6,
      narrative: "Aligned bullish. Score reflects EMA stack and SuperTrend alignment on captured window.",
      paragraphs: [
        "The technical leg scores the captured chart snapshot against Project APEX §4 rules.",
        "Technical score 82/100 is rated strong for directional conviction.",
        "Key drivers on this scan: EMA stack aligned bullish.",
      ],
      interpretation: "Actionable view: trend structure supports call-side expressions.",
      breakdown: [{ label: "Raw technical score", value: 82, note: "Base 50 + adjustments" }],
    },
    {
      id: "options",
      title: "Options",
      score: 70,
      weight: 0.2,
      weighted_contribution: 14,
      narrative: "Greeks quality score reflects chain fitness.",
      breakdown: [{ label: "Tradeable contracts", value: 2 }],
    },
    {
      id: "volatility",
      title: "Volatility",
      score: 72,
      weight: 0.25,
      weighted_contribution: 18,
      narrative: "IV rich versus HV.",
      breakdown: [{ label: "IV Rank", value: 55 }],
    },
    {
      id: "sentiment",
      title: "Sentiment",
      score: 65,
      weight: 0.15,
      weighted_contribution: 9.8,
      narrative: "Flow positive.",
      breakdown: [{ label: "Bias", value: "bullish" }],
    },
    {
      id: "fundamentals",
      title: "Fundamentals",
      score: 60,
      weight: 0.1,
      weighted_contribution: 6,
      narrative: "Steady growth.",
      breakdown: [{ label: "Layer score", value: 60 }],
    },
    {
      id: "risk",
      title: "Risk",
      score: 74,
      weight: 0,
      weighted_contribution: 0,
      narrative: "Execution tier maps composite to blocked, caution, or auto-exec.",
      breakdown: [{ label: "Composite", value: 78.5 }],
    },
  ],
};

const strategyPayload: StrategyLayer = {
  title: "Strategy playbook",
  selected_strategy: "Bull Call Spread",
  composite_score: 80,
  clears_threshold: true,
  direction: "bullish",
  vol_signal: "buy_premium",
  recommended_contract: {
    symbol: "XYZ",
    expiry: "2026-07-01",
    strike: 100,
    side: "call",
    contract_id: "C100",
  },
  what_is_this: "Debit spread with capped risk and defined reward.",
  why_recommended: "Composite meets the execution gate.",
  how_to_execute: "Buy the lower strike call and sell the higher strike call.",
  metrics: {
    max_loss: 120,
    max_profit: 380,
    net_debit_credit: 1.2,
    net_type: "debit",
    breakevens: [101.2],
    legs: [{ action: "buy", side: "call", strike: 100, mid: 2.1 }],
  },
  narrative: "Recommended: Bull Call Spread.",
};

describe("ApexScoreScan", () => {
  it("renders loading state without sections", () => {
    const html = renderToStaticMarkup(<ApexScoreScan />);
    expect(html).toContain('data-testid="apex-score-stage"');
    expect(html).toContain("Loading APEX composite score");
  });

  it("renders composite score and six collapsible sections", () => {
    const html = renderToStaticMarkup(<ApexScoreScan initial={apexPayload} />);
    expect(html).toContain('data-testid="apex-composite-value"');
    expect(html).toContain("78.5");
    expect(html).toContain('data-testid="apex-threshold-badge"');
    expect(html).toContain("Threshold met");
    expect(html).toContain('data-testid="apex-section-technicals"');
    expect(html).toContain('data-testid="apex-section-risk"');
    expect(html.match(/data-testid="apex-section-(?!toggle)[a-z]+"/g)?.length).toBe(6);
    expect(html).toContain("apex-synthesis-interpretation");
    expect(html).toContain("Actionable view");
    expect(html).toContain("Base 50 + adjustments");
  });
});

describe("StrategyScan", () => {
  it("renders loading state without a selected strategy", () => {
    const html = renderToStaticMarkup(<StrategyScan symbol="AAPL" />);
    expect(html).toContain('data-testid="strategy-stage"');
    expect(html).toContain("Loading strategy recommendation");
  });

  it("renders named strategy, copy blocks, and payoff metrics", () => {
    const html = renderToStaticMarkup(<StrategyScan symbol="AAPL" expiry="2026-07-01" initial={strategyPayload} />);
    expect(html).toContain("Bull Call Spread");
    expect(html).toContain('data-testid="strategy-what"');
    expect(html).toContain('data-testid="strategy-why"');
    expect(html).toContain('data-testid="strategy-how"');
    expect(html).toContain('data-testid="strategy-metrics"');
    expect(html).toContain("$120");
    expect(html).toContain("$1.20 debit");
  });

  it("renders blocked state without payoff metrics", () => {
    const html = renderToStaticMarkup(
      <StrategyScan
        symbol="AAPL"
        initial={{
          title: "Strategy",
          tradeable: false,
          execution_tier: "blocked",
          selected_strategy: "Not tradeable in current situation",
          composite_score: 45,
          clears_threshold: false,
          what_is_this: "",
          why_recommended: "Composite below minimum.",
          how_to_execute: "Re-scan when score improves.",
          metrics: { max_loss: null, max_profit: null, net_debit_credit: null, net_type: null, breakevens: [], legs: [] },
          narrative: "Blocked.",
        }}
      />,
    );
    expect(html).toContain("Not tradeable in current situation");
    expect(html).toContain('data-testid="strategy-not-tradeable"');
    expect(html).not.toContain('data-testid="strategy-metrics"');
  });

  it("hides payoff metrics for NO TRADE", () => {
    const html = renderToStaticMarkup(
      <StrategyScan
        symbol="AAPL"
        initial={{
          ...strategyPayload,
          selected_strategy: "NO TRADE — Insufficient Conviction",
          recommended_contract: null,
        }}
      />,
    );
    expect(html).toContain("NO TRADE");
    expect(html).toContain('data-no-trade="true"');
    expect(html).not.toContain('data-testid="strategy-metrics"');
  });
});
