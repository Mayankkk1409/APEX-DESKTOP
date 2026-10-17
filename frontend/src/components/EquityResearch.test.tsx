import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EquityResearch } from "./EquityResearch";
import { ResearchModeToggle } from "./ResearchModeToggle";
import { EQUITY_SLIDE_LAYERS, SCAN_SLIDE_LAYERS } from "../constants";

const plan = {
  action: "Buy",
  why: "The bullish scorecard cleared the gate.",
  horizon: { label: "Approximately two weeks", detail: "About ten trading days." },
  levels: { entry: 100, stop: 96, take_profit: 110, exit_target: 110, reward_risk: 2.5, entry_label: "Reference price." },
  scores: { technical: 72, sentiment: null, fundamental: 60, risk: 80, overall: 68.4, contributions: [], reweighted: ["sentiment"] },
  weight_policy: "Display weights are a midpoint, not a probability.",
  technical_evidence: ["Trend is up on the daily bars."],
  confirmed_patterns: [{ name: "Bull flag", direction: "bullish", strength: 80 }],
  developing_patterns: [],
  news: [{ headline: "Company raises outlook", published: "2026-10-13", source: "Alpaca News", url: "https://example.com/news" }],
  fundamentals_notes: ["Revenue trend: improving"],
  earnings: { date: "2026-11-02", confirmed: true, inside_holding_window: false, source: "NASDAQ" },
  short_note: "Borrow availability is not on this feed, so a short sale is not recommended.",
  analysts: [
    { analyst: "Ada Analyst", firm: "North Research", rating: "Buy", price_target: 120, currency: "USD", date: "2026-10-01", source: "NASDAQ", url: "https://example.com/rating" },
  ],
  analyst_basis: "Five most recent analyst ratings",
  analyst_note: "These are longer-horizon street targets. They are not this trade's take-profit.",
  risk_profile: "moderate",
  as_of: "2026-10-14",
  quote_session: "reference",
};

describe("EquityResearch", () => {
  it("keeps the options carousel and adds a separate equity sequence", () => {
    expect(SCAN_SLIDE_LAYERS).toContain("options_chain_greeks");
    expect(EQUITY_SLIDE_LAYERS).not.toContain("options_chain_greeks");
    expect(EQUITY_SLIDE_LAYERS).not.toContain("strategy");
  });

  it("shows one target, a horizon, and a sourced analyst on the plan", () => {
    const html = renderToStaticMarkup(<EquityResearch slide="equity_plan" plan={plan} />);
    expect(html).toContain("Buy");
    expect(html).toContain("Approximately two weeks");
    expect(html).toContain("110.00");
    expect(html).toContain("Ada Analyst");
    expect(html).toContain("North Research");
    expect(html).toContain("https://example.com/rating");
    expect(html).toContain("not this trade&#x27;s take-profit");
    expect(html).not.toContain("Place Trade");
    expect(html).not.toContain("Greeks");
  });

  it("offers equity and options without sending an order", () => {
    const html = renderToStaticMarkup(<ResearchModeToggle />);
    expect(html).toContain("Options");
    expect(html).toContain("Equity");
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("/api/orders");
  });

  it("explains equity risk and layer scores without an empty cell", () => {
    const saved = {
      ...plan,
      action: "Buy",
      why: "The bullish scorecard clears the gate and the bearish card does not.",
      risk_profile: "conservative",
      levels: {
        entry: 395.69,
        stop: 386.13,
        take_profit: 414.83,
        reward_risk: 2,
        stop_basis: "14-bar average true range",
      },
      scores: {
        technical: 79.6,
        sentiment: 60.6,
        fundamental: 82.7,
        risk: 60,
        overall: 77.5,
        reweighted: [],
        contributions: [
          { layer: "technical", weight: 0.6, score: 79.6, points: 47.76 },
          { layer: "sentiment", weight: 0.15, score: 60.6, points: 9.09 },
          { layer: "fundamental", weight: 0.25, score: 82.7, points: 20.68 },
        ],
      },
      scorecard: {
        bull: { earned: 8, possible: 12, passes: true, points: { structure: 2, trend: 2, volume: 1, fundamentals: 2, catalyst: 1, sentiment: 2 } },
        bear: { earned: 2, possible: 12, passes: false, points: { structure: 0, trend: 0, volume: 1, fundamentals: 0, catalyst: 1, sentiment: 0 } },
      },
      earnings: { date: "2026-10-13", confirmed: true, inside_holding_window: false, source: "UnitedHealth Group newsroom" },
      volume: { last: 1000, average: 800, ratio: 1.25, regime: "active" },
    };
    const risk = renderToStaticMarkup(<EquityResearch slide="equity_risk" plan={saved} />);
    const scores = renderToStaticMarkup(<EquityResearch slide="equity_scores" plan={saved} />);
    expect(risk).not.toContain("Unavailable");
    expect(scores).not.toContain("Unavailable");
    expect(risk).not.toContain("Greeks");
    expect(scores).not.toContain("Greeks");
    expect(risk).toContain("Earnings passed");
    expect(risk).toContain("9.56");
    expect(risk).toContain("2.42%");
    expect(scores).toContain("77.5");
    expect(scores).toContain("not a probability of profit");
    expect(scores).toContain("The gate on a 12-point card is 8");
    expect(scores).toContain("+21.2");
  });

  it("explains a downside case with the stop above the entry", () => {
    const html = renderToStaticMarkup(
      <EquityResearch
        slide="equity_plan"
        plan={{
          ...plan,
          action: "Avoid",
          trend: "down",
          scorecard: {
            bull: { earned: 2, possible: 12, passes: false },
            bear: { earned: 8, possible: 12, passes: true },
          },
          levels: { entry: 148.56, stop: 149.3, take_profit: 147.1, reward_risk: 1.97 },
        }}
      />,
    );
    expect(html).toContain("149.30");
    expect(html).toContain("147.10");
    expect(html).toContain("downside case is the one that fits");
    expect(html).toContain("above the entry");
    expect(html).toContain("below the entry");
  });

  it("shows a stop and take-profit when the saved action omitted them", () => {
    const html = renderToStaticMarkup(
      <EquityResearch
        slide="equity_plan"
        plan={{
          ...plan,
          action: "Hold",
          levels: { entry: 100, stop: null, take_profit: null, reward_risk: null },
        }}
      />,
    );
    expect(html).toContain("98.00");
    expect(html).toContain("104.00");
    expect(html).not.toContain("No stop is published");
    expect(html).not.toContain("No take-profit is published");
  });

  it("leaves missing sentiment blank", () => {
    const html = renderToStaticMarkup(<EquityResearch slide="equity_sentiment" plan={{ ...plan, news: [], scores: { ...plan.scores, sentiment: null } }} />);
    expect(html).toContain("left blank, not scored as neutral");
    expect(html).toContain("Unavailable");
  });
});
