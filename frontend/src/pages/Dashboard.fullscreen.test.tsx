import { readFileSync } from "node:fs";
import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store";
import { writePortfolioViewMode } from "../lib/portfolioViewMode";
import { createTestQueryClient } from "../test/queryClient";

vi.mock("../api", () => ({
  api: {
    quote: vi.fn(async () => ({ symbol: "SPX", name: "S&P 500", price: 5000 })),
    fundamentals: vi.fn(async () => ({})),
    expirations: vi.fn(async () => ({ expirations: [] })),
    watchlist: vi.fn(async () => ({ items: [] })),
    sentiment: vi.fn(async () => ({ items: [] })),
    portfolio: vi.fn(async () => ({ balance: 100000, buying_power: 100000, portfolio_value: 100000 })),
    positions: vi.fn(async () => ({ positions: [] })),
    dailyPnl: vi.fn(async () => ({ positions: [], book: [] })),
    search: vi.fn(async () => ({ hits: [{ symbol: "AAPL", name: "Apple" }] })),
    bars: vi.fn(async () => ({ bars: [] })),
    brokerageAccounts: vi.fn(),
    brokerageBalance: vi.fn(),
    brokeragePositions: vi.fn(),
    dismissBanner: vi.fn(),
    brokerage: vi.fn(),
    logout: vi.fn(async () => ({ ok: true })),
  },
  getAccessToken: () => null,
}));

import { Dashboard } from "./Dashboard";
import { TradingViewChart } from "../components/TradingViewChart";

describe("Options terminal chrome", () => {
  beforeEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({
      user: {
        id: "u1",
        full_name: "Test",
        username: "test",
        email: "t@example.com",
        account_mode: "paper_funded",
        brokerage_connected: false,
        connect_later_banner: false,
        first_login_completed: true,
        cash_balance: 100000,
        buying_power: 100000,
        portfolio_value: 100000,
        starting_balance: 100000,
      },
      showConnectModal: false,
      symbol: "SPX",
      timeframe: "1D",
    });
  });

  it("sends the logo and the Apex word to the portfolio route", () => {
    const html = renderDesk();
    expect(html).toContain('data-testid="apex-brand"');
    expect(html).toContain('href="/dashboard"');
    expect(html).toContain('aria-label="Apex"');
    expect(html).toContain('src="/brand/apex-logo.png"');
    expect(html).toContain(">APEX<");
    const brand = html.slice(html.indexOf('data-testid="apex-brand"'), html.indexOf('data-testid="ticker-search"'));
    expect(brand).toContain('src="/brand/apex-logo.png"');
    expect(brand).toContain(">APEX<");
  });

  it("keeps search, expiry, watchlist, and the ticker card while marking chrome that leaves", () => {
    const html = renderDesk();
    expect(html).toContain('data-testid="ticker-search"');
    expect(html).toContain('data-testid="expiry"');
    expect(html).toContain('data-testid="watchlist-toggle"');
    expect(html).toContain('data-testid="ticker-panel"');
    expect(html).toContain('data-chart-fullscreen="false"');
    for (const id of ["brand", "header-tools", "stats", "summary", "drawer", "footer"]) {
      expect(html).toContain(`data-desk-hide="${id}"`);
    }
    expect(html).toContain('data-testid="stat-balance"');
    expect(html).toContain('data-testid="positions"');
    expect(html).toContain('data-testid="sentiment"');
    expect(html).toContain('data-testid="chart-fullscreen"');
    expect(html).toContain('aria-label="Enter chart fullscreen"');
  });

  it("styles ticker rows and the fullscreen motion with existing tokens", () => {
    const css = readFileSync(new URL("../index.css", import.meta.url), "utf8");
    expect(css).toContain(".ticker-hit:hover");
    expect(css).toContain(".ticker-suggestions [role=\"option\"][aria-selected=\"true\"] .ticker-hit");
    expect(css).toContain("var(--apex-row-hover)");
    expect(css).toContain("var(--apex-gold)");
    expect(css).toContain("var(--apex-text)");
    expect(css).toContain("var(--apex-panel)");
    expect(css).toContain("140ms");
    expect(css).toContain("--desk-dur: 520ms");
    expect(css).toMatch(/prefers-reduced-motion:\s*reduce[\s\S]*--desk-dur:\s*140ms/);
    expect(css).toContain(".desk--chart-full .desk-ticker");
    expect(css).toContain(".desk-motion-sentinel");
  });

  it("places the fullscreen control on the chart without remounting for that prop", () => {
    const qc = createTestQueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <TradingViewChart symbol="SPX" timeframe="1D" fullscreen={false} fullscreenBusy onFullscreenToggle={() => undefined} />
      </QueryClientProvider>,
    );
    expect(html).toContain('data-testid="chart-fullscreen"');
    expect(html).toContain('aria-label="Enter chart fullscreen"');
    expect(html).toContain('data-testid="tv-embed"');
    const source = readFileSync(new URL("../components/TradingViewChart.tsx", import.meta.url), "utf8");
    expect(source).toContain("resizeEmbeddedChart");
    expect(source).toContain('data-desk-motion');
    expect(source).not.toMatch(/key=\{`\$\{mapped\}:\$\{timeframe\}:\$\{chrome\}:\$\{fullscreen/);
  });
});

function renderDesk() {
  const qc = createTestQueryClient();
  qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
  qc.setQueryData(["port"], { balance: 100000, buying_power: 100000, portfolio_value: 100000 });
  qc.setQueryData(["pos"], { positions: [] });
  qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
