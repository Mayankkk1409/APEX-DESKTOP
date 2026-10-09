import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const started: string[] = [];
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return {
    started,
    gate,
    release: () => release(),
  };
});

vi.mock("../api", () => ({
  api: {
    portfolio: vi.fn(async () => {
      h.started.push("portfolio");
      await h.gate;
      return {};
    }),
    positions: vi.fn(async () => {
      h.started.push("positions");
      await h.gate;
      return { positions: [] };
    }),
    orderHistory: vi.fn(async () => {
      h.started.push("orders");
      await h.gate;
      return { orders: [] };
    }),
    pnlHistory: vi.fn(async () => {
      h.started.push("graph");
      await h.gate;
      return { points: [] };
    }),
    dailyPnl: vi.fn(async () => {
      h.started.push("daily-pnl");
      await h.gate;
      return { positions: [], book: [] };
    }),
    overallPnl: vi.fn(async () => {
      h.started.push("overall-pnl");
      await h.gate;
      return { rows: [] };
    }),
  },
}));

import { refreshDeskQueries } from "./deskRefresh";

describe("refreshDeskQueries", () => {
  it("requests positions, daily P&L, and the equity graph together", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      refreshDeskQueries(qc);
      await vi.waitFor(() => {
        expect(h.started).toEqual(expect.arrayContaining(["positions", "daily-pnl", "graph"]));
      });
      const book = h.started.filter((name) => name === "positions" || name === "daily-pnl" || name === "graph");
      expect(book).toHaveLength(3);
    } finally {
      h.release();
      await h.gate;
    }
  });
});
