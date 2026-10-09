import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { DESK_STALE_MS } from "../lib/deskRefresh";
import { displayedOverallTotal } from "../lib/overallPnl";
import type { OverallPnlRow, PositionRow } from "../types";
import { useBrokerage } from "./useBrokerage";

/** Open brokerage positions have unrealized P&L only. Realized and fees are not on that payload. */
export function openPositionPnlRows(positions: readonly PositionRow[]): OverallPnlRow[] {
  return positions.map((position) => ({
    symbol: position.symbol,
    asset_class: position.asset_class ?? "us_equity",
    qty: position.qty,
    realized_pl: 0,
    unrealized_pl: position.unrealized_pl,
    total_pl: position.unrealized_pl,
    is_open: true,
  }));
}

/**
 * One overall total for the signed-in account view.
 * Paper reads `["overall-pnl"]` (`/api/portfolio/overall-pnl`).
 * A connected brokerage view sums that account's open positions with the same function.
 */
export function useAccountOverallPnl() {
  const brokerage = useBrokerage();
  const usingBrokerage = brokerage.usingBrokerage;
  const overall = useQuery({
    queryKey: ["overall-pnl"],
    queryFn: () => api.overallPnl(),
    enabled: !usingBrokerage,
    staleTime: DESK_STALE_MS,
  });

  const rows: OverallPnlRow[] = usingBrokerage
    ? openPositionPnlRows(brokerage.positionRows)
    : ((overall.data?.rows as OverallPnlRow[] | undefined) ?? []);
  const loading = usingBrokerage ? brokerage.positionsQuery.isLoading : overall.isLoading;
  const total = loading ? null : displayedOverallTotal(rows);

  return {
    rows,
    total,
    loading,
    error: overall.error,
    usingBrokerage,
  };
}
