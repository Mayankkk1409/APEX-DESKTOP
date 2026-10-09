import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useSession } from "../store";
import type { OrderHistoryRow, OrderPlacementResult } from "../types";

type PortfolioSnapshot = {
  balance?: number;
  buying_power?: number;
  portfolio_value?: number;
};

type OrderList = { orders?: OrderHistoryRow[] };

/** Skip a remount refetch while a fill still forces a fresh read. */
export const DESK_STALE_MS = 20_000;

/**
 * Pull portfolio, positions, orders, P&L, daily P&L, and the equity graph immediately.
 * The book, daily P&L, and graph start together — none waits on the others.
 * Inactive portfolio queries are fetched too, so a fill is not waiting on a poll.
 * Missing responses are left untouched — this does not invent bars or P&L.
 */
export function refreshDeskQueries(qc: QueryClient): void {
  const specs = [
    { queryKey: ["port"], queryFn: () => api.portfolio() },
    { queryKey: ["pos"], queryFn: () => api.positions() },
    { queryKey: ["orders"], queryFn: () => api.orderHistory() },
    { queryKey: ["pnl-history"], queryFn: () => api.pnlHistory() },
    { queryKey: ["daily-pnl"], queryFn: () => api.dailyPnl() },
    { queryKey: ["overall-pnl"], queryFn: () => api.overallPnl() },
  ] as const;
  for (const spec of specs) {
    // Drop a pre-fill request so it cannot satisfy this refresh for the 20s stale window.
    void qc.cancelQueries({ queryKey: spec.queryKey }).then(() => {
      void qc.fetchQuery({ ...spec, staleTime: 0 });
    });
  }
  void qc.invalidateQueries({ queryKey: ["brokerage"], refetchType: "all" });
}

/** Write balances the order response already returned. Does not create a book if none is cached. */
export function applyReturnedFillBalances(
  qc: QueryClient,
  fill: Pick<OrderPlacementResult, "balance" | "buying_power" | "portfolio_value">,
): void {
  const user = useSession.getState().user;
  if (user) {
    const next = { ...user };
    let changed = false;
    if (typeof fill.balance === "number") {
      next.cash_balance = fill.balance;
      changed = true;
    }
    if (typeof fill.buying_power === "number") {
      next.buying_power = fill.buying_power;
      changed = true;
    }
    if (typeof fill.portfolio_value === "number") {
      next.portfolio_value = fill.portfolio_value;
      changed = true;
    }
    if (changed) useSession.getState().setUser(next);
  }

  qc.setQueryData<PortfolioSnapshot>(["port"], (current) => {
    const patch: PortfolioSnapshot = {};
    if (typeof fill.balance === "number") patch.balance = fill.balance;
    if (typeof fill.buying_power === "number") patch.buying_power = fill.buying_power;
    if (typeof fill.portfolio_value === "number") patch.portfolio_value = fill.portfolio_value;
    if (!Object.keys(patch).length) return current;
    return { ...(current ?? {}), ...patch };
  });
}

/** Prepend legs the fill response already returned. Skips when order history has not loaded. */
export function applyReturnedOrderRows(qc: QueryClient, result: OrderPlacementResult): void {
  const legs = result.legs_filled ?? [];
  if (!legs.length) return;
  qc.setQueryData<OrderList>(["orders"], (current) => {
    if (!current?.orders) return current;
    const known = new Set(current.orders.map((row) => row.id));
    const fresh: OrderHistoryRow[] = [];
    for (const leg of legs) {
      if (!leg.id || known.has(leg.id)) continue;
      fresh.push({
        id: leg.id,
        symbol: leg.symbol,
        side: leg.side,
        qty: leg.qty,
        order_type: leg.order_type || "limit",
        fill_price: leg.fill_price ?? null,
        status: result.status,
        asset_class: leg.asset_class || result.asset_class,
        created_at: null,
        filled_at: null,
      });
    }
    if (!fresh.length) return current;
    return { ...current, orders: [...fresh, ...current.orders] };
  });
}
