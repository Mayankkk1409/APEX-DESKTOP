import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { displayedOverallTotal, positionUnrealizedCents } from "../lib/overallPnl";
import { fmtBalance, fmtMoney } from "../lib/portfolioFormat";
import { writePortfolioViewMode } from "../lib/portfolioViewMode";
import { createTestQueryClient } from "../test/queryClient";
import { useSession } from "../store";
import type { OverallPnlRow } from "../types";

vi.mock("../api", () => ({
  api: {
    portfolio: vi.fn(async () => ({
      balance: 100000,
      buying_power: 100000,
      portfolio_value: 100000,
      starting_balance: 25000,
      day_pl: 0,
    })),
    overallPnl: vi.fn(async () => ({ rows: [] })),
    pnlHistory: vi.fn(async () => ({ starting_balance: 25000, account_mode: "paper_funded", points: [] })),
    positions: vi.fn(async () => ({ positions: [] })),
    orderHistory: vi.fn(async () => ({ orders: [] })),
    brokerageAccounts: vi.fn(async () => ({ connection_status: null, accounts: [] })),
    getSettings: vi.fn(async () => ({ risk_profile: "moderate" })),
    syncSettings: vi.fn(async () => ({ ok: true })),
    resetPaperBalance: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(async () => ({ ok: true })),
  },
}));

vi.mock("../components/BrokerageConnectionPanel", () => ({
  BrokerageConnectionPanel: () => <div data-testid="brokerage-panel" />,
}));

import { Portfolio } from "./Portfolio";
import { Settings } from "./Settings";

function row(partial: Partial<OverallPnlRow> & Pick<OverallPnlRow, "symbol">): OverallPnlRow {
  const realized = partial.realized_pl ?? 0;
  const unrealized = partial.unrealized_pl ?? 0;
  return {
    symbol: partial.symbol,
    asset_class: partial.asset_class ?? "us_equity",
    qty: partial.qty ?? 1,
    realized_pl: realized,
    unrealized_pl: unrealized,
    total_pl: partial.total_pl ?? realized + unrealized,
    is_open: partial.is_open ?? true,
    fees: partial.fees,
  };
}

function fieldText(html: string, testId: string): string[] {
  const pattern = new RegExp(`data-testid="${testId}"[^>]*>([^<]*)`, "g");
  return [...html.matchAll(pattern)].map((match) => match[1].trim());
}

function renderScreens(rows: OverallPnlRow[]) {
  const qc = createTestQueryClient();
  qc.setQueryData(["overall-pnl"], { rows });
  qc.setQueryData(["port"], {
    balance: 100000,
    buying_power: 100000,
    portfolio_value: 100000,
    starting_balance: 25000,
    day_pl: 0,
  });
  const shell = (node: React.ReactNode) =>
    renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>,
    );
  return {
    settings: shell(<Settings />),
    portfolio: shell(<Portfolio />),
  };
}

describe("Settings and Portfolio total P&L", () => {
  beforeEach(() => {
    writePortfolioViewMode("paper");
    useSession.setState({
      user: {
        id: "u1",
        username: "trader",
        account_mode: "paper_funded",
        cash_balance: 100000,
        portfolio_value: 100000,
        buying_power: 100000,
        starting_balance: 25000,
      } as never,
      portfolioViewMode: "paper",
      selectedBrokerageAccountId: null,
    });
  });

  const shortUnrealized = positionUnrealizedCents(1.1, 1.5, -2, 100) / 100;

  const books: { name: string; rows: OverallPnlRow[] }[] = [
    { name: "no trades", rows: [] },
    {
      name: "a winning closed trade",
      rows: [row({ symbol: "AAPL", qty: 0, realized_pl: 250, unrealized_pl: 0, is_open: false })],
    },
    {
      name: "a losing open position",
      rows: [row({ symbol: "MSFT", qty: 10, realized_pl: 0, unrealized_pl: -19.75, is_open: true })],
    },
    {
      name: "mixed",
      rows: [
        row({ symbol: "AAPL", qty: 0, realized_pl: 40.1, unrealized_pl: 0, is_open: false }),
        row({ symbol: "MSFT", qty: 5, realized_pl: 0, unrealized_pl: -15.4, is_open: true }),
        row({ symbol: "NVDA", qty: 0, realized_pl: -10, unrealized_pl: 0, is_open: false }),
      ],
    },
    {
      name: "a short option",
      rows: [
        row({
          symbol: "AAPL260918P00150000",
          asset_class: "us_option",
          qty: -2,
          realized_pl: 0,
          unrealized_pl: shortUnrealized,
          is_open: true,
        }),
      ],
    },
  ];

  it.each(books)("shows the same cent total for $name", ({ rows }) => {
    const expected = fmtMoney(displayedOverallTotal(rows));
    const equityMinusStarting = fmtMoney(100000 - 25000);
    const { settings, portfolio } = renderScreens(rows);
    const settingsTotals = fieldText(settings, "settings-pnl");
    const portfolioTotals = fieldText(portfolio, "overall-pnl-total-value");

    expect(settingsTotals).toEqual([expected]);
    expect(portfolioTotals.length).toBeGreaterThan(0);
    expect(portfolioTotals.every((value) => value === expected)).toBe(true);
    expect(settingsTotals[0]).toBe(portfolioTotals[0]);
    expect(expected).not.toBe(equityMinusStarting);
  });

  it("shows the portfolio header on the chart when history ends on a different value", () => {
    const qc = createTestQueryClient();
    qc.setQueryData(["overall-pnl"], { rows: [] });
    qc.setQueryData(["port"], {
      balance: 100000,
      buying_power: 100000,
      portfolio_value: 100000,
      starting_balance: 25000,
      day_pl: 0,
    });
    qc.setQueryData(["pnl-history"], {
      starting_balance: 25000,
      account_mode: "paper_funded",
      points: [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 90000 },
        { t: "2026-09-01T00:00:00Z", portfolio_value: 91000 },
      ],
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Portfolio />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const header = fieldText(html, "portfolio-header-balance");
    const chart = fieldText(html, "pnl-chart-value");
    expect(header).toEqual([`Portfolio value ${fmtBalance(100000)}`]);
    expect(chart).toEqual([fmtBalance(100000)]);
    expect(html).not.toContain("$91,000");
    expect(html).not.toContain("$90,000");
  });
});
