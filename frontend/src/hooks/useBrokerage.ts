import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api";
import type { BrokerageAccount, BrokerageBalance, BrokeragePosition } from "../lib/brokerageApi";
import { mapBrokeragePositions } from "../lib/brokerageMapper";
import { readPortfolioViewMode } from "../lib/portfolioViewMode";
import { useSession } from "../store";
import type { PortfolioViewMode } from "../types";
import type { PositionRow } from "../types";

export function resolveActiveAccountId(
  accounts: BrokerageAccount[],
  selectedBrokerageAccountId: string | null,
): string | null {
  if (selectedBrokerageAccountId) {
    if (accounts.length === 0 || accounts.some((account) => account.id === selectedBrokerageAccountId)) {
      return selectedBrokerageAccountId;
    }
  }
  return accounts[0]?.id ?? null;
}

export type BrokerageStats = {
  balance: number;
  buying_power: number;
  portfolio_value: number;
  day_pnl: number | null;
};

export function useBrokerage() {
  const selectedBrokerageAccountId = useSession((state) => state.selectedBrokerageAccountId);
  const setSelectedBrokerageAccountId = useSession((state) => state.setSelectedBrokerageAccountId);
  const storeViewMode = useSession((state) => state.portfolioViewMode);
  const portfolioViewMode =
    typeof window === "undefined" ? readPortfolioViewMode() : storeViewMode;
  const setPortfolioViewMode = useSession((state) => state.setPortfolioViewMode);

  const accountsQuery = useQuery({
    queryKey: ["brokerage", "accounts"],
    queryFn: () =>
      api.brokerageAccounts() as Promise<{ connection_status: string | null; accounts: BrokerageAccount[] }>,
  });

  const accounts = accountsQuery.data?.accounts ?? [];
  const connected = accounts.length > 0 || accountsQuery.data?.connection_status === "connected";

  const activeId = resolveActiveAccountId(accounts, selectedBrokerageAccountId);
  const usingBrokerage = portfolioViewMode === "brokerage" && Boolean(activeId);

  useEffect(() => {
    if (!accountsQuery.isFetched) return;
    if (accounts.length === 0) {
      if (selectedBrokerageAccountId) setSelectedBrokerageAccountId(null);
      return;
    }
    if (!selectedBrokerageAccountId || !accounts.some((a) => a.id === selectedBrokerageAccountId)) {
      setSelectedBrokerageAccountId(accounts[0].id);
    }
  }, [accounts, accountsQuery.isFetched, selectedBrokerageAccountId, setSelectedBrokerageAccountId]);

  const balanceQuery = useQuery({
    queryKey: ["brokerage", "balance", activeId],
    queryFn: () => api.brokerageBalance(activeId!) as Promise<BrokerageBalance>,
    enabled: usingBrokerage && Boolean(activeId),
  });

  const positionsQuery = useQuery({
    queryKey: ["brokerage", "positions", activeId],
    queryFn: () => api.brokeragePositions(activeId!),
    enabled: usingBrokerage && Boolean(activeId),
  });

  const activeAccount = accounts.find((a) => a.id === activeId) ?? null;
  const balance = balanceQuery.data as BrokerageBalance | undefined;
  const positionRows: PositionRow[] = mapBrokeragePositions(
    (positionsQuery.data?.positions as BrokeragePosition[] | undefined) ?? [],
  );

  const stats: BrokerageStats | null =
    usingBrokerage && balance
      ? {
          balance: balance.cash_balance,
          buying_power: balance.buying_power,
          portfolio_value: balance.total_equity,
          day_pnl: balance.day_pnl,
        }
      : null;

  function selectViewMode(mode: PortfolioViewMode) {
    setPortfolioViewMode(mode);
  }

  return {
    connected,
    usingBrokerage,
    portfolioViewMode,
    selectViewMode,
    accounts,
    activeAccount,
    activeAccountId: activeId,
    setActiveAccountId: setSelectedBrokerageAccountId,
    balance,
    positionRows,
    stats,
    accountsQuery,
    balanceQuery,
    positionsQuery,
  };
}
