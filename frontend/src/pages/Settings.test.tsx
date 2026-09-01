import { QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";
import { useSession } from "../store";
import { createTestQueryClient } from "../test/queryClient";

const store: Record<string, string> = {};

vi.mock("../api", () => ({
  api: {
    portfolio: vi.fn(async () => ({
      balance: 25000,
      buying_power: 25000,
      portfolio_value: 25000,
      day_pl: 0,
      starting_balance: 25000,
    })),
    syncSettings: vi.fn(async () => ({ ok: true })),
    resetPaperBalance: vi.fn(async () => ({ username: "trader" })),
    deleteAccount: vi.fn(async () => ({ ok: true })),
  },
}));

vi.mock("../hooks/useBrokerage", () => ({
  useBrokerage: () => ({
    usingBrokerage: false,
    connected: false,
    stats: null,
    accounts: [],
    activeAccount: null,
    activeAccountId: null,
    accountsQuery: { isLoading: false },
    balanceQuery: { isFetching: false },
    positionsQuery: { isFetching: false },
  }),
}));

vi.mock("../components/BrokerageConnectionPanel", () => ({
  BrokerageConnectionPanel: () => <div data-testid="brokerage-panel" />,
}));

describe("Settings page", () => {
  beforeEach(() => {
    Object.keys(store).forEach((k) => delete store[k]);
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store[k] ?? null,
      setItem: (k: string, v: string) => {
        store[k] = v;
      },
      removeItem: (k: string) => {
        delete store[k];
      },
      clear: () => {
        Object.keys(store).forEach((k) => delete store[k]);
      },
    });
    vi.stubGlobal("document", {
      documentElement: {
        dataset: {} as DOMStringMap,
        style: {} as CSSStyleDeclaration,
        removeAttribute: () => undefined,
      },
    });
    useSession.setState({
      user: {
        id: "u1",
        username: "trader",
        account_mode: "paper_funded",
        cash_balance: 25000,
        portfolio_value: 25000,
        buying_power: 25000,
        starting_balance: 25000,
      } as never,
    });
  });

  it("renders account, risk, appearance, and security sections", () => {
    const qc = createTestQueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(html).toContain('data-testid="settings-page"');
    expect(html).toContain('data-testid="settings-account"');
    expect(html).toContain('data-testid="settings-risk"');
    expect(html).toContain('data-testid="settings-appearance"');
    expect(html).toContain('data-testid="settings-security"');
    expect(html).toContain('data-testid="settings-auto-exec-toggle"');
    expect(html).toContain('data-testid="settings-delete-account"');
    expect(html).toContain('data-testid="settings-paper-audit"');
  });
});
