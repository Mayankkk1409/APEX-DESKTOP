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
    portfolio: vi.fn(async () => ({
      balance: 100000,
      buying_power: 100000,
      portfolio_value: 100000,
      day_pl: 500,
      day_pct: 0.5,
    })),
    positions: vi.fn(async () => ({
      positions: [{ id: "p1", symbol: "AAPL", qty: 10, avg_cost: 150, current: 160, market_value: 1600, unrealized_pl: 100, asset_class: "us_equity" }],
    })),
    dailyPnl: vi.fn(async () => ({ positions: [], book: [] })),
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

import { Dashboard } from "./Dashboard";

describe("Dashboard paper vs brokerage isolation", () => {
  beforeEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({
      user: {
        id: "u1",
        full_name: "Test",
        username: "test",
        email: "t@example.com",
        account_mode: "paper_funded",
        brokerage_connected: true,
        connect_later_banner: false,
        first_login_completed: true,
        cash_balance: 100000,
        buying_power: 100000,
        portfolio_value: 100000,
        starting_balance: 100000,
      },
      selectedBrokerageAccountId: "acc-fidelity",
      portfolioViewMode: "paper",
      showConnectModal: false,
      symbol: "SPX",
    });
  });

  it("shows paper stats when view mode is paper even if brokerage is connected", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], {
      connection_status: "connected",
      accounts: [
        {
          id: "acc-fidelity",
          account_name: "Individual",
          account_type: "margin",
          broker_name: "Fidelity",
          account_number_masked: "****9999",
          sync_status: "ok",
          last_synced_at: "2026-08-27T12:00:00Z",
        },
      ],
    });
    qc.setQueryData(["brokerage", "balance", "acc-fidelity"], {
      cash_balance: 5000,
      buying_power: 10000,
      total_equity: 50000,
      day_pnl: 200,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["port"], {
      balance: 100000,
      buying_power: 100000,
      portfolio_value: 100000,
      day_pl: 500,
      day_pct: 0.5,
    });
    qc.setQueryData(["pos"], {
      positions: [{ id: "p1", symbol: "AAPL", qty: 10, avg_cost: 150, current: 160, market_value: 1600, unrealized_pl: 100, asset_class: "us_equity" }],
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain("100,000");
    expect(html).not.toContain("50,000");
    expect(html).toContain("AAPL");
    expect(html).not.toContain("Fidelity");
  });

  it("shows brokerage stats when view mode is brokerage", () => {
    writePortfolioViewMode("brokerage");
    useSession.setState({ portfolioViewMode: "brokerage", selectedBrokerageAccountId: "acc-fidelity" });
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], {
      connection_status: "connected",
      accounts: [
        {
          id: "acc-fidelity",
          account_name: "Individual",
          account_type: "margin",
          broker_name: "Fidelity",
          account_number_masked: "****9999",
          sync_status: "ok",
          last_synced_at: "2026-08-27T12:00:00Z",
        },
      ],
    });
    qc.setQueryData(["brokerage", "balance", "acc-fidelity"], {
      cash_balance: 5000,
      buying_power: 10000,
      total_equity: 50000,
      day_pnl: 200,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    qc.setQueryData(["brokerage", "positions", "acc-fidelity"], {
      positions: [
        {
          symbol: "MSFT",
          quantity: 5,
          average_cost: 400,
          current_price: 420,
          market_value: 2100,
          unrealized_pnl: 100,
          currency: "USD",
          day_pnl: 25,
        },
      ],
    });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["quote", "MSFT"], { symbol: "MSFT", name: "Microsoft", price: 420, change: 5 });
    qc.setQueryData(["port"], {
      balance: 100000,
      buying_power: 100000,
      portfolio_value: 100000,
      day_pl: 500,
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="stat-pv"');
    expect(html).toContain("50,000");
    expect(html).toContain("MSFT");
    expect(html).not.toContain("AAPL");
  });

  it("shows every daily P&L point for an open position, including an unavailable day", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["port"], { balance: 100000, buying_power: 100000, portfolio_value: 100000, day_pl: 500 });
    qc.setQueryData(["pos"], {
      positions: [{ id: "p1", symbol: "AAPL", qty: 10, avg_cost: 150, current: 160, market_value: 1600, unrealized_pl: 100, asset_class: "us_equity" }],
    });
    qc.setQueryData(["daily-pnl"], {
      positions: [
        {
          id: "p1",
          symbol: "AAPL",
          days: [
            { date: "2026-10-01", pnl: 12.5, status: "marked" },
            { date: "2026-10-02", pnl: -4, status: "marked" },
            { date: "2026-10-05", pnl: null, status: "unavailable" },
          ],
        },
      ],
      book: [
        { date: "2026-10-01", pnl: 12.5, status: "marked" },
        { date: "2026-10-02", pnl: -4, status: "marked" },
        { date: "2026-10-05", pnl: null, status: "unavailable" },
      ],
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="position-daily-row-p1"');
    expect(html).toContain('data-date="2026-10-01"');
    expect(html).toContain('data-date="2026-10-02"');
    expect(html).toContain('data-date="2026-10-05"');
    expect(html).toContain("+$12.5");
    expect(html).toContain("-$4");
    expect(html).toContain("unavailable");
    expect(html).toContain('data-testid="book-daily-pnl"');
    expect(html).toContain("100");
  });

  it("shows book dollars when at least one session is marked", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
    qc.setQueryData(["quote", "SPX"], { symbol: "SPX", name: "S&P 500", price: 5000 });
    qc.setQueryData(["port"], { balance: 100000, buying_power: 100000, portfolio_value: 100000, day_pl: 500 });
    qc.setQueryData(["pos"], {
      positions: [{ id: "p1", symbol: "AAPL", qty: 10, avg_cost: 150, current: 160, market_value: 1600, unrealized_pl: 100, asset_class: "us_equity" }],
    });
    qc.setQueryData(["daily-pnl"], {
      positions: [
        {
          id: "p1",
          symbol: "AAPL",
          days: [{ date: "2026-10-06", pnl: 18.5, status: "marked" }],
        },
      ],
      book: [{ date: "2026-10-06", pnl: 18.5, status: "marked" }],
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="day-pl-summary"');
    expect(html).toContain("Day P&amp;L 18.5");
    expect(html).toContain("+$18.5");
    expect(html).not.toContain("Day P&amp;L unavailable");
  });
});
