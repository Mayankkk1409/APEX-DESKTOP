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
});
