import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTestQueryClient } from "../test/queryClient";
import { useSession } from "../store";

vi.mock("../api", () => ({
  api: {
    watchlist: vi.fn(async () => ({ items: [{ symbol: "AAPL", name: "Apple Inc.", price: null }] })),
    portfolio: vi.fn(async () => ({ balance: null, buying_power: 1000, portfolio_value: 1000 })),
    marketSession: vi.fn(async () => ({ phase: "closed", trading_day: false, as_of: "", last_open: "", timezone: "America/New_York" })),
    recentScans: vi.fn(async () => ({ scans: [] })),
    brokerageAccounts: vi.fn(async () => ({ connection_status: null, accounts: [] })),
    brokerageBalance: vi.fn(),
    logout: vi.fn(async () => ({ ok: true })),
  },
  getAccessToken: () => null,
}));

import { HomeDashboard } from "./HomeDashboard";

describe("HomeDashboard", () => {
  beforeEach(() => {
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
        cash_balance: 1000,
        buying_power: 1000,
        portfolio_value: 1000,
        starting_balance: 1000,
      },
    });
  });

  it("labels featured names and does not print an unknown cash balance as zero", () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter>
          <HomeDashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(html).toContain('data-testid="home-dashboard"');
    expect(html).toContain("Featured");
    expect(html).not.toContain("Popular");
    expect(html).toContain("Paper");
    expect(html).toContain("Brokerage");
    expect(html).toContain('href="/dashboard"');
  });
});
