import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store";
import { writePortfolioViewMode } from "../lib/portfolioViewMode";
import { createTestQueryClient } from "../test/queryClient";

vi.mock("../api", () => ({
  api: {
    portfolio: vi.fn(async () => ({ balance: 0, buying_power: 0, portfolio_value: 0 })),
    pnlHistory: vi.fn(async () => ({ starting_balance: 25000, account_mode: "paper_funded", points: [] })),
    overallPnl: vi.fn(async () => ({ rows: [] })),
    positions: vi.fn(async () => ({ positions: [] })),
    orderHistory: vi.fn(async () => ({ orders: [] })),
    closePosition: vi.fn(),
    logout: vi.fn(async () => ({ ok: true })),
    brokerageAccounts: vi.fn(),
    brokerageBalance: vi.fn(),
    brokeragePositions: vi.fn(),
    brokerageEquityHistory: vi.fn(),
    brokerageOrders: vi.fn(),
    getSettings: vi.fn(async () => ({ risk_profile: "moderate" })),
    syncSettings: vi.fn(async () => ({ ok: true })),
  },
}));

import { Portfolio } from "./Portfolio";

describe("Portfolio brokerage integration", () => {
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
    });
  });

  it("shows connected brokerage equity, chart timeframes, and positions", () => {
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
    qc.setQueryData(["brokerage", "balance", "acc-1"], {
      cash_balance: 5000,
      buying_power: 10000,
      total_equity: 33000,
      day_pnl: 50,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    qc.setQueryData(["brokerage", "positions", "acc-1"], {
      positions: [
        {
          symbol: "MSFT",
          quantity: 3,
          average_cost: 400,
          current_price: 420,
          market_value: 1260,
          unrealized_pnl: 60,
          currency: "USD",
        },
      ],
    });
    qc.setQueryData(["brokerage", "equity-history", "acc-1"], {
      starting_balance: 30000,
      account_mode: "real_brokerage",
      points: [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 30000, balance: 5000, cumulative_pl: 0 },
        { t: "2026-08-27T12:00:00Z", portfolio_value: 33000, balance: 5000, cumulative_pl: 3000 },
      ],
    });
    qc.setQueryData(["brokerage", "orders", "acc-1"], {
      orders: [
        {
          id: "ord-1",
          symbol: "MSFT",
          side: "buy",
          qty: 3,
          order_type: "market",
          fill_price: 400,
          status: "EXECUTED",
          asset_class: "us_equity",
          created_at: "2026-08-20T12:00:00Z",
          filled_at: "2026-08-20T12:00:00Z",
        },
      ],
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Portfolio />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('data-testid="portfolio-header-balance"');
    expect(html).toContain("Equity (connected brokerage)");
    expect(html).toContain("33,000");
    expect(html).toContain("Equity");
    expect(html).not.toContain('data-testid="pnl-chart-balance"');
    expect(html).toContain('data-testid="portfolio-positions"');
    expect(html).toContain("MSFT");
    expect(html).not.toContain('data-testid="close-position-');
    expect(html).toContain('data-testid="pnl-chart-timeframe"');
    expect(html).toContain('data-testid="pnl-tf-1M"');
    expect(html).toContain('data-testid="portfolio-risk-profile-select"');
    expect(html.indexOf('data-testid="portfolio-risk-profile"')).toBeLessThan(
      html.indexOf('data-testid="portfolio-overall-section"'),
    );
    expect(html).toContain('data-testid="overall-pnl-total"');
    expect(html).toContain("Overall total P&amp;L");
    expect(html).toContain("+$60");
    expect(html).not.toContain("+$3,000");
    expect(html).toContain('data-chart-engine="apex-equity"');
    expect(html).toContain('data-testid="portfolio-brokerage-account"');
    expect(html).not.toContain('data-testid="portfolio-paper-context"');
    expect(html).toContain('data-testid="logout-btn"');
  });
});
