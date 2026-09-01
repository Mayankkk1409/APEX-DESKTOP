import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { resolveActiveAccountId, useBrokerage } from "./useBrokerage";
import { writePortfolioViewMode } from "../lib/portfolioViewMode";
import { useSession } from "../store";
import { createTestQueryClient } from "../test/queryClient";

vi.mock("../api", () => ({
  api: {
    brokerageAccounts: vi.fn(),
    brokerageBalance: vi.fn(),
    brokeragePositions: vi.fn(),
  },
  getAccessToken: () => "test-token",
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

function BrokerageProbe() {
  const b = useBrokerage();
  return (
    <div
      data-testid="brokerage-probe"
      data-mode={b.portfolioViewMode}
      data-using={String(b.usingBrokerage)}
      data-balance={b.stats?.balance ?? 0}
      data-equity={b.stats?.portfolio_value ?? 0}
      data-positions={b.positionRows.map((p) => p.symbol).join(",")}
      data-account={b.activeAccountId ?? ""}
    />
  );
}

function renderProbe(qc: QueryClient, accountId: string, viewMode: "paper" | "brokerage" = "brokerage") {
  writePortfolioViewMode(viewMode);
  useSession.setState({ selectedBrokerageAccountId: accountId, portfolioViewMode: viewMode });
  qc.setQueryData(["brokerage", "accounts"], { connection_status: "connected", accounts: mockAccounts });
  qc.setQueryData(["brokerage", "balance", accountId], {
    cash_balance: accountId === "acc-margin" ? 12500.5 : 3000,
    buying_power: accountId === "acc-margin" ? 25000 : 6000,
    total_equity: accountId === "acc-margin" ? 48200.75 : 12000,
    day_pnl: 10,
    currency: "USD",
    as_of_timestamp: "2026-08-27T12:00:00Z",
  });
  qc.setQueryData(["brokerage", "positions", accountId], {
    positions:
      accountId === "acc-margin"
        ? [
            {
              symbol: "NVDA",
              quantity: 5,
              average_cost: 800,
              current_price: 920,
              market_value: 4600,
              unrealized_pnl: 600,
              currency: "USD",
            },
          ]
        : [],
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <BrokerageProbe />
    </QueryClientProvider>,
  );
}

describe("useBrokerage", () => {
  beforeEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({ selectedBrokerageAccountId: null, portfolioViewMode: "paper" });
    vi.mocked(api.brokerageAccounts).mockResolvedValue({
      connection_status: "connected",
      accounts: mockAccounts,
    });
    vi.mocked(api.brokerageBalance).mockImplementation(async (id: string) => ({
      cash_balance: id === "acc-margin" ? 12500.5 : 3000,
      buying_power: id === "acc-margin" ? 25000 : 6000,
      total_equity: id === "acc-margin" ? 48200.75 : 12000,
      day_pnl: 10,
      currency: "USD",
      as_of_timestamp: "2026-08-27T12:00:00Z",
    }));
    vi.mocked(api.brokeragePositions).mockImplementation(async (id: string) => ({
      positions:
        id === "acc-margin"
          ? [
              {
                symbol: "NVDA",
                quantity: 5,
                average_cost: 800,
                current_price: 920,
                market_value: 4600,
                unrealized_pnl: 600,
                currency: "USD",
              },
            ]
          : [],
    }));
  });

  afterEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({ selectedBrokerageAccountId: null, portfolioViewMode: "paper" });
  });

  it("exposes selected account stats and mapped positions", () => {
    const qc = createTestQueryClient();
    const html = renderProbe(qc, "acc-margin");
    expect(html).toContain('data-using="true"');
    expect(html).toContain('data-balance="12500.5"');
    expect(html).toContain('data-equity="48200.75"');
    expect(html).toContain('data-positions="NVDA"');
    expect(html).toContain('data-account="acc-margin"');
  });

  it("resolves selected account id from shared store", () => {
    expect(resolveActiveAccountId(mockAccounts, "acc-ira")).toBe("acc-ira");
    expect(resolveActiveAccountId(mockAccounts, null)).toBe("acc-margin");
    expect(resolveActiveAccountId([], "acc-ira")).toBe("acc-ira");
    expect(resolveActiveAccountId([], null)).toBeNull();
  });

  it("persists account selection in zustand store", () => {
    useSession.getState().setSelectedBrokerageAccountId("acc-ira");
    expect(useSession.getState().selectedBrokerageAccountId).toBe("acc-ira");
  });

  it("stays in paper mode when no brokerage accounts exist", () => {
    useSession.setState({ portfolioViewMode: "paper" });
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: null, accounts: [] });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <BrokerageProbe />
      </QueryClientProvider>,
    );
    expect(html).toContain('data-using="false"');
    expect(html).toContain('data-balance="0"');
  });

  it("uses brokerage data only when portfolio view mode is brokerage", () => {
    useSession.setState({ portfolioViewMode: "brokerage" });
    const qc = createTestQueryClient();
    const html = renderProbe(qc, "acc-margin");
    expect(html).toContain('data-using="true"');
  });

  it("shows paper mode even when brokerage is connected if view mode is paper", () => {
    useSession.setState({ portfolioViewMode: "paper", selectedBrokerageAccountId: "acc-margin" });
    const qc = createTestQueryClient();
    qc.setQueryData(["brokerage", "accounts"], { connection_status: "connected", accounts: mockAccounts });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <BrokerageProbe />
      </QueryClientProvider>,
    );
    expect(html).toContain('data-using="false"');
  });
});
