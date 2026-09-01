import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ApexLogo } from "../components/ApexLogo";
import { LegalFooter } from "../components/LegalFooter";
import { LogoutButton } from "../components/LogoutButton";
import { PnlChart } from "../components/PnlChart";
import { useBrokerage } from "../hooks/useBrokerage";
import { filterPnlPoints, type PnlTimeframe } from "../lib/pnlTimeframe";
import { assetLabel, fmtBalance, fmtMoney, fmtPlain, fmtTs } from "../lib/portfolioFormat";
import { useSession } from "../store";
import type { OrderHistoryRow, OverallPnlRow, PositionRow } from "../types";

function Collapsible({
  title,
  testId,
  defaultOpen = true,
  children,
}: {
  title: string;
  testId: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-xl border border-line bg-panel" data-testid={testId}>
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-left font-display text-lg text-gold"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {title}
        <span aria-hidden className="text-sm text-white/50">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && <div className="border-t border-line px-4 pb-4">{children}</div>}
    </section>
  );
}

function brokerageOverallRows(positions: PositionRow[]): OverallPnlRow[] {
  return positions.map((p) => ({
    symbol: p.symbol,
    asset_class: p.asset_class ?? "us_equity",
    qty: p.qty,
    realized_pl: 0,
    unrealized_pl: p.unrealized_pl,
    total_pl: p.unrealized_pl,
    is_open: true,
  }));
}

export function Portfolio() {
  const qc = useQueryClient();
  const { user, setUser } = useSession();
  const brokerage = useBrokerage();
  const [chartTimeframe, setChartTimeframe] = useState<PnlTimeframe>("MAX");

  const usingBrokerage = brokerage.usingBrokerage;

  const summary = useQuery({
    queryKey: ["port"],
    queryFn: () => api.portfolio(),
    enabled: !usingBrokerage,
  });
  const paperPnlHistory = useQuery({
    queryKey: ["pnl-history"],
    queryFn: () => api.pnlHistory(),
    enabled: !usingBrokerage,
    retry: 2,
  });
  const brokerageEquityHistory = useQuery({
    queryKey: ["brokerage", "equity-history", brokerage.activeAccountId],
    queryFn: () => api.brokerageEquityHistory(brokerage.activeAccountId!),
    enabled: usingBrokerage && Boolean(brokerage.activeAccountId),
    retry: 2,
  });
  const overall = useQuery({
    queryKey: ["overall-pnl"],
    queryFn: () => api.overallPnl(),
    enabled: !usingBrokerage,
  });
  const positions = useQuery({
    queryKey: ["pos"],
    queryFn: () => api.positions(),
    enabled: !usingBrokerage,
  });
  const paperOrders = useQuery({
    queryKey: ["orders"],
    queryFn: () => api.orderHistory(),
    enabled: !usingBrokerage,
  });
  const brokerageOrders = useQuery({
    queryKey: ["brokerage", "orders", brokerage.activeAccountId],
    queryFn: () => api.brokerageOrders(brokerage.activeAccountId!),
    enabled: usingBrokerage && Boolean(brokerage.activeAccountId),
  });

  const close = useMutation({
    mutationFn: (positionId: string) => api.closePosition(positionId),
    onSuccess: (res) => {
      if (user) {
        setUser({
          ...user,
          cash_balance: res.balance,
          buying_power: res.buying_power,
          portfolio_value: res.portfolio_value,
        });
      }
      void qc.invalidateQueries({ queryKey: ["port"] });
      void qc.invalidateQueries({ queryKey: ["pos"] });
      void qc.invalidateQueries({ queryKey: ["pnl-history"] });
      void qc.invalidateQueries({ queryKey: ["overall-pnl"] });
      void qc.invalidateQueries({ queryKey: ["orders"] });
    },
  });

  const historyQuery = usingBrokerage ? brokerageEquityHistory : paperPnlHistory;
  const rawPoints = historyQuery.data?.points ?? [];
  const points = useMemo(() => filterPnlPoints(rawPoints, chartTimeframe), [rawPoints, chartTimeframe]);
  const fallbackBalance =
    historyQuery.data?.starting_balance ??
    summary.data?.starting_balance ??
    user?.starting_balance ??
    summary.data?.portfolio_value ??
    brokerage.stats?.portfolio_value ??
    user?.portfolio_value ??
    0;
  const openPositions: PositionRow[] = usingBrokerage
    ? brokerage.positionRows
    : ((positions.data?.positions as PositionRow[] | undefined) ?? []);
  const positionsLoading = usingBrokerage ? brokerage.positionsQuery.isLoading : positions.isLoading;
  const headerBalance = usingBrokerage && brokerage.stats
    ? brokerage.stats.portfolio_value
    : (summary.data?.portfolio_value ?? user?.portfolio_value);
  const headerLabel = usingBrokerage ? "Equity (connected brokerage)" : "Portfolio value";
  const orderRows: OrderHistoryRow[] = usingBrokerage
    ? ((brokerageOrders.data?.orders as OrderHistoryRow[] | undefined) ?? [])
    : ((paperOrders.data?.orders as OrderHistoryRow[] | undefined) ?? []);
  const ordersLoading = usingBrokerage ? brokerageOrders.isLoading : paperOrders.isLoading;
  const overallRows: OverallPnlRow[] = usingBrokerage
    ? brokerageOverallRows(openPositions)
    : ((overall.data?.rows as OverallPnlRow[] | undefined) ?? []);
  const overallLoading = usingBrokerage ? positionsLoading : overall.isLoading;
  const loadError =
    summary.error?.message ??
    historyQuery.error?.message ??
    positions.error?.message ??
    overall.error?.message ??
    paperOrders.error?.message ??
    brokerageOrders.error?.message ??
    null;

  return (
    <div className="min-h-screen bg-[#07070a] text-white" data-testid="portfolio-page">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <ApexLogo size={36} className="shrink-0" />
          <p className="font-display text-xl tracking-[0.2em]">APEX</p>
          <Link to="/app" className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-gold hover:bg-gold/10" data-testid="desk-link">
            Dashboard
          </Link>
        </div>
        <LogoutButton />
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        <div>
          <h1 className="font-display text-2xl">Portfolio</h1>
          <p className="mt-1 text-sm text-white/50" data-testid="portfolio-header-balance">
            {headerLabel} {fmtBalance(headerBalance)}
          </p>
          {usingBrokerage && brokerage.activeAccount && (
            <p className="mt-1 text-xs text-white/40" data-testid="portfolio-brokerage-account">
              {brokerage.activeAccount.account_name} · {brokerage.activeAccount.broker_name}
            </p>
          )}
          {!usingBrokerage && (
            <p className="mt-1 text-xs text-white/40" data-testid="portfolio-paper-context">
              Paper trading account
            </p>
          )}
        </div>

        {loadError && (
          <p className="rounded-md border border-red-500/40 bg-red-950/30 px-3 py-2 text-sm text-red-300" role="alert">
            Could not load portfolio: {loadError}. Check that you are signed in and the API is running.
          </p>
        )}

        <section data-testid="portfolio-pnl-section">
          <PnlChart
            points={points}
            fallbackBalance={fallbackBalance}
            timeframe={chartTimeframe}
            onTimeframeChange={setChartTimeframe}
            valueLabel={usingBrokerage ? "Equity" : "Portfolio value"}
          />
          {historyQuery.isFetching && !historyQuery.data && (
            <p className="mt-2 text-xs text-white/40" data-testid="portfolio-chart-loading">
              Loading portfolio history…
            </p>
          )}
        </section>

        <Collapsible title="Current Portfolio" testId="portfolio-positions-section">
          <p className="mt-2 text-xs text-white/40">
            {usingBrokerage
              ? "Open positions from your connected brokerage — read-only, synced with the dashboard."
              : "Open positions from your desk — same data as the dashboard table."}
          </p>
          {positionsLoading ? (
            <p className="mt-3 text-sm text-white/40">Loading positions…</p>
          ) : openPositions.length === 0 ? (
            <p className="mt-3 text-sm text-white/40">No open positions.</p>
          ) : (
            <table className="mt-3 w-full text-left text-sm" data-testid="portfolio-positions">
              <thead className="text-bronze">
                <tr>
                  <th className="py-2">Symbol</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Avg cost</th>
                  <th>Current</th>
                  <th>Unrealized P&amp;L</th>
                  <th>Market value</th>
                  {!usingBrokerage && <th className="text-right">Action</th>}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-2">{p.symbol}</td>
                    <td>{assetLabel(p.asset_class ?? "us_equity")}</td>
                    <td>{fmtPlain(p.qty)}</td>
                    <td>{fmtPlain(p.avg_cost)}</td>
                    <td>{fmtPlain(p.current)}</td>
                    <td className={p.unrealized_pl >= 0 ? "num-up" : "num-down"}>{fmtMoney(p.unrealized_pl)}</td>
                    <td>{fmtMoney(p.market_value)}</td>
                    {!usingBrokerage && (
                      <td className="text-right">
                        <button
                          type="button"
                          className="rounded border border-line px-2 py-1 text-xs text-gold hover:bg-gold/10 disabled:opacity-40"
                          data-testid={`close-position-${p.id}`}
                          disabled={close.isPending}
                          onClick={() => close.mutate(p.id)}
                        >
                          Close
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Collapsible>

        <Collapsible title="Order History" testId="portfolio-orders-section" defaultOpen={false}>
          {ordersLoading ? (
            <p className="mt-3 text-sm text-white/40">Loading orders…</p>
          ) : orderRows.length === 0 ? (
            <p className="mt-3 text-sm text-white/40">
              {usingBrokerage ? "No recent brokerage orders." : "No orders yet."}
            </p>
          ) : (
            <table className="mt-3 w-full text-left text-sm" data-testid="portfolio-orders">
              <thead className="text-bronze">
                <tr>
                  <th className="py-2">Time</th>
                  <th>Side</th>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Fill</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orderRows.map((o) => (
                  <tr key={o.id} className="border-t border-line">
                    <td className="py-2 text-white/60">{fmtTs(o.filled_at ?? o.created_at)}</td>
                    <td>{o.side.toUpperCase()}</td>
                    <td>{o.symbol}</td>
                    <td>{fmtPlain(o.qty)}</td>
                    <td>{fmtPlain(o.fill_price)}</td>
                    <td>{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Collapsible>

        <Collapsible title="Overall P&amp;L" testId="portfolio-overall-section" defaultOpen={false}>
          {overallLoading ? (
            <p className="mt-3 text-sm text-white/40">Loading P&amp;L breakdown…</p>
          ) : overallRows.length === 0 ? (
            <p className="mt-3 text-sm text-white/40">No trade history yet.</p>
          ) : (
            <table className="mt-3 w-full text-left text-sm">
              <thead className="text-bronze">
                <tr>
                  <th className="py-2">Symbol</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Realized</th>
                  <th>Unrealized</th>
                  <th>Total</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {overallRows.map((r) => (
                  <tr key={r.symbol} className="border-t border-line">
                    <td className="py-2">{r.symbol}</td>
                    <td>{assetLabel(r.asset_class)}</td>
                    <td>{fmtPlain(r.qty)}</td>
                    <td className={r.realized_pl >= 0 ? "num-up" : "num-down"}>{fmtMoney(r.realized_pl)}</td>
                    <td className={r.unrealized_pl >= 0 ? "num-up" : "num-down"}>{fmtMoney(r.unrealized_pl)}</td>
                    <td className={r.total_pl >= 0 ? "num-up" : "num-down"}>{fmtMoney(r.total_pl)}</td>
                    <td>{r.is_open ? "Open" : "Closed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Collapsible>
      </main>

      <LegalFooter className="px-4 pb-6" />
    </div>
  );
}
