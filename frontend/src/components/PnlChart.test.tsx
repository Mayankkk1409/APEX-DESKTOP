import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { PnlChart } from "./PnlChart";

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  AreaSeries: "AreaSeries",
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
  }),
}));

describe("PnlChart", () => {
  it("renders timeframe controls when handler provided", () => {
    const html = renderToStaticMarkup(
      <PnlChart
        points={[{ t: "2026-08-01T00:00:00Z", portfolio_value: 10000 }]}
        fallbackBalance={10000}
        timeframe="1M"
        onTimeframeChange={() => {}}
      />,
    );
    expect(html).toContain('data-testid="pnl-chart-timeframe"');
    expect(html).toContain('data-testid="pnl-tf-MAX"');
    expect(html).toContain('data-testid="pnl-tf-YTD"');
    expect(html).toContain("$10,000");
    expect(html).toContain("Portfolio value");
  });

  it("uses portfolio_value instead of cash balance for chart header", () => {
    const html = renderToStaticMarkup(
      <PnlChart
        points={[{ t: "2026-08-01T00:00:00Z", portfolio_value: 33000, balance: 5000 }]}
        fallbackBalance={5000}
      />,
    );
    expect(html).toContain("$33,000");
    expect(html).not.toContain("$5,000");
  });

  it("shows a loading state instead of the empty chart while history is in flight", () => {
    const html = renderToStaticMarkup(<PnlChart points={[]} pending />);
    expect(html).toContain('data-testid="portfolio-chart-loading"');
    expect(html).not.toContain('data-testid="pnl-chart-empty"');
    expect(html).not.toContain("<iframe");
  });

  it("shows an empty state and no TradingView embed when history is missing", () => {
    const html = renderToStaticMarkup(<PnlChart points={[]} fallbackBalance={10000} />);
    expect(html).toContain('data-testid="pnl-chart-empty"');
    expect(html).toContain("No equity history yet.");
    expect(html).toContain('data-chart-engine="apex-equity"');
    expect(html).not.toContain("tradingview");
    expect(html).not.toContain("<iframe");
  });

  it("shows the overall total P&L under the equity chart", () => {
    const html = renderToStaticMarkup(
      <PnlChart
        points={[{ t: "2026-08-01T00:00:00Z", portfolio_value: 33000, cumulative_pl: 3000 }]}
        headlineEquity={33000}
        overallTotal={3000}
      />,
    );
    expect(html).toContain('data-chart-engine="apex-equity"');
    expect(html).toContain('data-testid="pnl-chart-canvas"');
    expect(html).toContain('data-testid="pnl-chart-overall-total"');
    expect(html).toContain("Overall total P&amp;L");
    expect(html).toContain("+$3,000");
    expect(html).toContain("num-up");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("tradingview");
  });

  it("labels the chart as the in-app equity engine when history exists", () => {
    const html = renderToStaticMarkup(
      <PnlChart points={[{ t: "2026-08-01T00:00:00Z", portfolio_value: 12000 }]} headlineEquity={12500} />,
    );
    expect(html).toContain('data-chart-engine="apex-equity"');
    expect(html).toContain('data-testid="pnl-chart-canvas"');
    expect(html).toContain("$12,500");
    expect(html).not.toContain("<iframe");
  });
});
