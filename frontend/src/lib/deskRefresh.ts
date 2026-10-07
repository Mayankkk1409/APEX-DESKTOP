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

/**
 * Pull portfolio, positions, orders, P&L, and the equity graph immediately.
 * Inactive portfolio queries are fetched too, so a fill is not waiting on a poll.
 * Missing responses are left untouched — this does not invent bars or P&L.
 */
export function refreshDeskQueries(qc: QueryClient): void {
  void qc.fetchQuery({ queryKey: ["port"], queryFn: () => api.portfolio() });
  void qc.fetchQuery({ queryKey: ["pos"], queryFn: () => api.positions() });
  void qc.fetchQuery({ queryKey: ["orders"], queryFn: () => api.orderHistory() });
  void qc.fetchQuery({ queryKey: ["pnl-history"], queryFn: () => api.pnlHistory() });
  void qc.fetchQuery({ queryKey: ["overall-pnl"], queryFn: () => api.overallPnl() });
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
    if (!current) return current;
    return {
      ...current,
      ...(typeof fill.balance === "number" ? { balance: fill.balance } : {}),
      ...(typeof fill.buying_power === "number" ? { buying_power: fill.buying_power } : {}),
      ...(typeof fill.portfolio_value === "number" ? { portfolio_value: fill.portfolio_value } : {}),
    };
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
