import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrokerageConnectionPanel } from "./BrokerageConnectionPanel";
import { useSession } from "../store";
import { writePortfolioViewMode } from "../lib/portfolioViewMode";
import { createTestQueryClient } from "../test/queryClient";

vi.mock("../api", () => ({
  api: {
    brokerageRegister: vi.fn(),
    brokeragePortalUrl: vi.fn(),
    brokerageSync: vi.fn(async () => ({ ok: true, connection_status: "connected", account_count: 2 })),
    brokerageAccounts: vi.fn(),
    brokerageBalance: vi.fn(),
    brokeragePositions: vi.fn(),
    brokerageDisconnect: vi.fn(),
  },
}));

import { api } from "../api";

const mockAccounts = [
  {
    id: "acc-margin",
    account_name: "Margin",
    account_type: "margin",
    broker_name: "Alpaca",
    account_number_masked: "****1234",
    sync_status: "ok",
    last_synced_at: "2026-08-27T12:00:00Z",
  },
  {
    id: "acc-ira",
    account_name: "IRA",
    account_type: "ira",
    broker_name: "Alpaca",
    account_number_masked: "****5678",
    sync_status: "ok",
    last_synced_at: "2026-08-27T12:00:00Z",
  },
];

function renderPanel(qc: QueryClient) {
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BrokerageConnectionPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BrokerageConnectionPanel", () => {
  beforeEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({ selectedBrokerageAccountId: null, portfolioViewMode: "paper" });
    vi.mocked(api.brokerageAccounts).mockResolvedValue({ connection_status: null, accounts: [] });
    vi.mocked(api.brokerageBalance).mockResolvedValue({
      cash_balance: 0,
      buying_power: 0,
      total_equity: 0,
      day_pnl: null,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    vi.mocked(api.brokeragePositions).mockResolvedValue({ positions: [] });
  });

  it("renders connect CTA when no accounts are linked", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
    const html = renderPanel(qc);
    expect(html).toContain('data-testid="brokerage-panel"');
    expect(html).toContain('data-testid="brokerage-connect"');
    expect(html).toContain('data-testid="portfolio-view-mode"');
    expect(html).toContain("Paper Trading");
  });

  it("renders account dropdown for a single linked account", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], {
      connection_status: "connected",
      accounts: [mockAccounts[0]],
    });
    qc.setQueryData(["brokerage", "balance", "acc-margin"], {
      cash_balance: 1000,
      buying_power: 2000,
      total_equity: 5000,
      day_pnl: 10,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    qc.setQueryData(["brokerage", "positions", "acc-margin"], { positions: [] });
    writePortfolioViewMode("brokerage");
    useSession.setState({ selectedBrokerageAccountId: "acc-margin", portfolioViewMode: "brokerage" });

    const html = renderPanel(qc);
    expect(html).toContain('data-testid="brokerage-account-select"');
    expect(html).not.toContain('data-testid="brokerage-account-label"');
  });

  it("renders account dropdown without duplicate balance or positions tables", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: "connected", accounts: mockAccounts });
    qc.setQueryData(["brokerage", "balance", "acc-margin"], {
      cash_balance: 1000,
      buying_power: 2000,
      total_equity: 5000,
      day_pnl: 10,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    });
    qc.setQueryData(["brokerage", "positions", "acc-margin"], { positions: [] });
    writePortfolioViewMode("brokerage");
    useSession.setState({ selectedBrokerageAccountId: "acc-margin", portfolioViewMode: "brokerage" });

    const html = renderPanel(qc);
    expect(html).toContain('data-testid="brokerage-account-select"');
    expect(html).toContain("Margin · Alpaca · ****1234");
    expect(html).toContain("Brokerage account");
    expect(html).toContain('data-testid="brokerage-refresh"');
    expect(html).not.toContain('data-testid="brokerage-stats"');
    expect(html).not.toContain('data-testid="brokerage-positions"');
  });
});
