import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useBrokerage } from "../hooks/useBrokerage";
import { useSession } from "../store";
import type { PortfolioViewMode } from "../types";

export function BrokerageConnectionPanel() {
  const qc = useQueryClient();
  const { user, setSelectedBrokerageAccountId } = useSession();
  const {
    connected,
    portfolioViewMode,
    selectViewMode,
    accounts,
    activeAccount,
    activeAccountId,
    setActiveAccountId,
    accountsQuery,
    balanceQuery,
    positionsQuery,
  } = useBrokerage();
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [callbackMsg, setCallbackMsg] = useState<string | null>(null);

  const paperBalance = user?.portfolio_value ?? user?.cash_balance ?? 100_000;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connectedParam = params.get("connected");
    if (connectedParam === "true") {
      setCallbackMsg("Brokerage connected successfully.");
      selectViewMode("brokerage");
      void api.brokerageSync().finally(() => {
        qc.invalidateQueries({ queryKey: ["brokerage"] });
      });
    } else if (connectedParam === "false") {
      setCallbackMsg("Brokerage connection was not completed.");
      void api.brokerageSync().finally(() => {
        qc.invalidateQueries({ queryKey: ["brokerage"] });
      });
    }
    if (connectedParam) {
      params.delete("connected");
      const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
      window.history.replaceState({}, "", next);
    }
  }, [qc, selectViewMode]);

  const portal = useMutation({
    mutationFn: () => api.brokeragePortalUrl(),
    onSuccess: (data) => {
      window.location.assign(data.url);
    },
  });

  const refresh = useMutation({
    mutationFn: () => api.brokerageSync(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["brokerage"] });
    },
  });

  const disconnect = useMutation({
    mutationFn: () => api.brokerageDisconnect(activeAccountId!),
    onSuccess: () => {
      setDisconnectOpen(false);
      setSelectedBrokerageAccountId(null);
      selectViewMode("paper");
      qc.invalidateQueries({ queryKey: ["brokerage"] });
    },
  });

  const register = useMutation({
    mutationFn: () => api.brokerageRegister(),
    onSuccess: () => setDisclosureOpen(true),
  });

  const brokerLabel = accounts[0]?.broker_name || "your broker";
  const lastSynced = activeAccount?.last_synced_at;
  const syncPending = balanceQuery.isFetching || positionsQuery.isFetching;

  function onViewModeChange(mode: PortfolioViewMode) {
    selectViewMode(mode);
  }

  return (
    <section className="rounded-xl border border-line bg-panel px-4 py-3" data-testid="brokerage-panel">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-bronze">Account data source</p>
          <span
            className={`apex-badge mt-1 ${connected ? "apex-badge-live" : "apex-badge-offline"}`}
            data-testid="brokerage-status-badge"
          >
            {connected ? "Connected" : "Not connected"}
          </span>
        </div>
        {!connected ? (
          <button
            type="button"
            data-testid="brokerage-connect"
            className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink"
            onClick={() => register.mutate()}
            disabled={register.isPending}
          >
            Connect brokerage
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="brokerage-refresh"
              className="rounded-md border border-line px-3 py-1.5 text-sm text-gold"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
            >
              Refresh
            </button>
            <button
              type="button"
              data-testid="brokerage-disconnect"
              className="rounded-md border border-line px-3 py-1.5 text-sm"
              onClick={() => setDisconnectOpen(true)}
            >
              Disconnect
            </button>
          </div>
        )}
      </div>

      <div className="mt-3 space-y-2">
        <label className="block text-xs text-bronze" htmlFor="portfolio-view-mode">
          View
        </label>
        <select
          id="portfolio-view-mode"
          data-testid="portfolio-view-mode"
          className="w-full rounded-md border border-line bg-panel px-3 py-2 text-sm"
          value={portfolioViewMode}
          onChange={(e) => onViewModeChange(e.target.value as PortfolioViewMode)}
        >
          <option value="paper" data-testid="portfolio-view-paper">
            Paper Trading · ${paperBalance.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </option>
          {connected && accounts.length > 0 && (
            <option value="brokerage" data-testid="portfolio-view-brokerage">
              Connected Brokerage
            </option>
          )}
        </select>
        {portfolioViewMode === "paper" && (
          <p className="text-xs text-faint" data-testid="portfolio-view-paper-hint">
            Paper account is always available — ${paperBalance.toLocaleString(undefined, { maximumFractionDigits: 0 })} simulated balance.
          </p>
        )}
      </div>

      {callbackMsg && (
        <p className="mt-2 text-sm text-champagne" data-testid="brokerage-callback-msg">
          {callbackMsg}
        </p>
      )}

      {(accountsQuery.isError || register.isError) && (
        <p className="mt-2 text-sm text-bronze" data-testid="brokerage-error">
          {((register.error ?? accountsQuery.error) as Error).message}
        </p>
      )}

      {portfolioViewMode === "brokerage" && connected && accounts.length > 0 && (
        <div className="mt-3 space-y-2">
          <label className="block text-xs text-bronze" htmlFor="brokerage-account-select">
            Brokerage account
          </label>
          <select
            id="brokerage-account-select"
            data-testid="brokerage-account-select"
            className="w-full rounded-md border border-line bg-panel px-3 py-2 text-sm"
            value={activeAccountId ?? ""}
            onChange={(e) => setActiveAccountId(e.target.value)}
          >
            {accounts.map((acc) => (
              <option key={acc.id} value={acc.id}>
                {acc.account_name} · {acc.broker_name} · {acc.account_number_masked}
              </option>
            ))}
          </select>
          {lastSynced && (
            <p className="text-xs text-faint" data-testid="brokerage-last-synced">
              Last synced {new Date(lastSynced).toLocaleString()}
              {syncPending ? " · updating…" : ""}
            </p>
          )}
          {(balanceQuery.isError || positionsQuery.isError) && (
            <p className="text-sm text-bronze" data-testid="brokerage-sync-error">
              {(balanceQuery.error ?? positionsQuery.error as Error)?.message}
            </p>
          )}
        </div>
      )}

      {!connected && (
        <p className="mt-2 text-xs text-faint">
          Connect via SnapTrade for live read-only account data. Paper trading remains available without a connection.
        </p>
      )}

      {disclosureOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--apex-backdrop)]" data-testid="brokerage-disclosure">
          <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6">
            <h2 className="font-display text-xl">Connect your brokerage</h2>
            <p className="mt-3 text-sm text-champagne/70">
              You&apos;ll be redirected to {brokerLabel}&apos;s official login page. APEX does not receive or store your
              brokerage username or password. This connection is read-only — APEX cannot place trades on your behalf.
            </p>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                className="flex-1 rounded-md bg-gold py-2 text-ink"
                data-testid="brokerage-disclosure-continue"
                onClick={() => portal.mutate()}
                disabled={portal.isPending}
              >
                Continue
              </button>
              <button type="button" className="flex-1 rounded-md border border-line py-2" onClick={() => setDisclosureOpen(false)}>
                Cancel
              </button>
            </div>
            {portal.isError && <p className="mt-3 text-sm text-bronze">{(portal.error as Error).message}</p>}
          </div>
        </div>
      )}

      {disconnectOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--apex-backdrop)]" data-testid="brokerage-disconnect-modal">
          <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6">
            <h2 className="font-display text-xl">Disconnect brokerage?</h2>
            <p className="mt-2 text-sm text-subtle">APEX will remove this read-only connection and stop syncing data.</p>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                className="flex-1 rounded-md bg-gold py-2 text-ink"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                Disconnect
              </button>
              <button type="button" className="flex-1 rounded-md border border-line py-2" onClick={() => setDisconnectOpen(false)}>
                Cancel
              </button>
            </div>
            {disconnect.isError && <p className="mt-3 text-sm text-bronze">{(disconnect.error as Error).message}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
