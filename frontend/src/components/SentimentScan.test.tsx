import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { SentimentLayer } from "../types";
import { createTestQueryClient } from "../test/queryClient";
import { SentimentScan } from "./SentimentScan";

vi.mock("../api", () => ({
  api: {
    sentimentDeep: vi.fn(async () => {
      throw new Error("initial data should render without a refetch");
    }),
  },
}));

const FORBIDDEN = "No live Alpaca headlines are stored for this desk yet.";

function layer(news: Partial<SentimentLayer["components"]["news"]>): SentimentLayer {
  return {
    title: "Sentiment",
    symbol: "AAPL",
    score: null,
    score_0_100: null,
    band: "Unavailable",
    bias: "unavailable",
    weights: {},
    weights_applied: {},
    narrative: "No recent news for AAPL from Alpaca News.",
    evidence: {},
    earnings_alert: { active: false, dte: null, next_date: null, message: "", source: null },
    components: {
      news: {
        status: "empty",
        score: null,
        count: 0,
        method: "lexicon_v1",
        source: null,
        articles: [],
        ...news,
      },
      options_flow: {
        status: "unavailable",
        score: null,
        label: "unavailable",
        window: "",
        call_volume: null,
        put_volume: null,
        call_notional_proxy: null,
        put_notional_proxy: null,
        net_notional_proxy: null,
        unusual_activity_count: null,
        source: null,
      },
      social: { status: "unavailable", score: null, label: "unavailable", source: null },
      put_call: {
        status: "unavailable",
        score: null,
        ratio: null,
        signal: "unavailable",
        rule: "",
        source: null,
        basis: "",
      },
    },
  };
}

function render(news: Partial<SentimentLayer["components"]["news"]>) {
  const client = createTestQueryClient();
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <SentimentScan symbol="AAPL" expiry="" initial={layer(news)} />
    </QueryClientProvider>,
  );
}

describe("SentimentScan news", () => {
  it("shows the neutral empty sentence and never the forbidden copy", () => {
    const html = render({});
    expect(html).toContain("No recent news for AAPL from Alpaca News.");
    expect(html).not.toContain(FORBIDDEN);
    expect(html).not.toContain("desk");
    expect(html).not.toContain("stored");
  });

  it("shows the provider error and a retry control", () => {
    const html = render({ status: "unavailable", error: "News feed HTTP 503" });
    expect(html).toContain("News feed HTTP 503.");
    expect(html).toContain('data-testid="sentiment-news-retry"');
    expect(html).not.toContain(FORBIDDEN);
  });

  it("maps a provider article with source, timestamp, and link", () => {
    const html = render({
      status: "live",
      source: "Alpaca News",
      count: 1,
      articles: [
        {
          headline: "Microsoft raises dividend after record profit",
          summary: "Board approved a higher payout.",
          source: "benzinga",
          author: null,
          url: "https://example.com/msft",
          published_at: "2026-10-01T14:30:00Z",
          symbols: ["MSFT"],
          nlp_score: 53.2,
          nlp_method: "lexicon_v1",
        },
      ],
    });
    expect(html).toContain("Microsoft raises dividend after record profit");
    expect(html).toContain("benzinga");
    expect(html).toContain("2026-10-01 14:30");
    expect(html).toContain('href="https://example.com/msft"');
    expect(html).toContain("lexicon_v1");
    expect(html).not.toContain(FORBIDDEN);
  });
});
