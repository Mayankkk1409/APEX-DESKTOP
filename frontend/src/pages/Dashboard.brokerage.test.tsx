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
    portfolio: vi.fn(async () => ({ balance: 0, buying_power: 0, portfolio_value: 0 })),
    positions: vi.fn(async () => ({ positions: [] })),
    search: vi.fn(async () => ({ hits: [] })),
    brokerageAccounts: vi.fn(),
    brokerageBalance: vi.fn(),
    brokeragePositions: vi.fn(),
    dismissBanner: vi.fn(),
    brokerage: vi.fn(),
    logout: vi.fn(async () => ({ ok: true })),
  },
  getAccessToken: () => null,
}));

vi.mock("../components/TradingViewChart", () => ({
  TradingViewChart: () => null,
}));

import { api } from "../api";
import { Dashboard } from "./Dashboard";

const mockBalance = {
  cash_balance: 9000,
  buying_power: 18000,
  total_equity: 42000,
  day_pnl: 150,
  currency: "USD",
  as_of_timestamp: "2026-08-27T12:00:00Z",
};

describe("Dashboard brokerage integration", () => {
  beforeEach(() => {
    writePortfolioViewMode("brokerage");
    useSession.setState({
      user: {
        id: "u1",
        full_name: "Test",
        username: "test",
        email: "t@example.com",
        account_mode: "real_brokerage",
        brokerage_connected: true,
        connect_later_banner: false,
        first_login_completed: true,
        cash_balance: 0,
        buying_power: 0,
        portfolio_value: 0,
        starting_balance: null,
      },
      selectedBrokerageAccountId: "acc-1",
      portfolioViewMode: "brokerage",
      showConnectModal: false,
      symbol: "SPX",
    });
    vi.mocked(api.brokerageAccounts).mockResolvedValue({
      connection_status: "connected",
      accounts: [
        {
          id: "acc-1",
          account_name: "Margin",
          account_type: "margin",
          broker_name: "Alpaca",
          account_number_masked: "****1234",
          sync_status: "ok",
          last_synced_at: "2026-08-27T12:00:00Z",
        },
      ],
    });
    vi.mocked(api.brokerageBalance).mockResolvedValue(mockBalance);
    vi.mocked(api.brokeragePositions).mockResolvedValue({
      positions: [
        {
          symbol: "TSLA",
          quantity: 2,
          average_cost: 200,
          current_price: 250,
          market_value: 500,
          unrealized_pnl: 100,
          currency: "USD",
        },
      ],
    });
  });

  it("renders connected brokerage stats and positions in dashboard sections", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], {
      connection_status: "connected",
      accounts: [
        {
          id: "acc-1",
          account_name: "Margin",
          account_type: "margin",
          broker_name: "Alpaca",
          account_number_masked: "****1234",
          sync_status: "ok",
          last_synced_at: "2026-08-27T12:00:00Z",
        },
      ],
    });
    qc.setQueryData(["brokerage", "balance", "acc-1"], mockBalance);
    qc.setQueryData(["brokerage", "positions", "acc-1"], {
      positions: [
        {
          symbol: "TSLA",
          quantity: 2,
          average_cost: 200,
          current_price: 250,
          market_value: 500,
          unrealized_pnl: 100,
          currency: "USD",
          day_pnl: 25,
        },
      ],
    });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["quote", "TSLA"], { symbol: "TSLA", name: "Tesla", price: 250, change: 5 });
    qc.setQueryData(["port"], { balance: 0, buying_power: 0, portfolio_value: 0, day_pl: 99, day_pct: 1 });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="stat-balance"');
    expect(html).toContain("9,000");
    expect(html).toContain('data-testid="stat-bp"');
    expect(html).toContain("18,000");
    expect(html).toContain('data-testid="stat-pv"');
    expect(html).toContain("42,000");
    expect(html).toContain('data-testid="positions"');
    expect(html).toContain("TSLA");
    expect(html).toContain("500");
    expect(html).toContain("Daily P/L");
    expect(html).toContain("25");
    expect(html).toContain('data-testid="day-pl-summary"');
    expect(html).toContain("150");
    expect(html).not.toContain("99");
    expect(html).toContain('data-testid="logout-btn"');
  });

  it("does not show stale paper day P/L while brokerage balance is loading", () => {
    writePortfolioViewMode("brokerage");
    useSession.setState({ selectedBrokerageAccountId: "acc-1", portfolioViewMode: "brokerage" });
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], {
      connection_status: "connected",
      accounts: [
        {
          id: "acc-1",
          account_name: "Margin",
          account_type: "margin",
          broker_name: "Alpaca",
          account_number_masked: "****1234",
          sync_status: "ok",
          last_synced_at: "2026-08-27T12:00:00Z",
        },
      ],
    });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["port"], { balance: 0, buying_power: 0, portfolio_value: 0, day_pl: 99, day_pct: 1 });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="day-pl-summary"');
    expect(html).not.toContain("99");
  });

  it("uses paper portfolio day P/L when brokerage is not connected", () => {
    writePortfolioViewMode("paper");
    useSession.setState({ selectedBrokerageAccountId: null, portfolioViewMode: "paper" });
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["port"], { balance: 10000, buying_power: 10000, portfolio_value: 12000, day_pl: 250, day_pct: 2.08 });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="day-pl-summary"');
    expect(html).toContain("250");
  });
});
