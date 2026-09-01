import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ApexLogo } from "../components/ApexLogo";
import { LegalFooter } from "../components/LegalFooter";
import { LogoutButton } from "../components/LogoutButton";
import { PositionCertificateModal } from "../components/PositionCertificateModal";
import { SettingsGearLink } from "../components/SettingsGearLink";
import { PnlChart } from "../components/PnlChart";
import { useBrokerage } from "../hooks/useBrokerage";
import { defaultAccountLabel, usePositionCertificate } from "../hooks/usePositionCertificate";
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
        <span aria-hidden className="text-sm text-subtle">
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
  const cert = usePositionCertificate({
    isPaper: !brokerage.usingBrokerage,
    accountLabel: defaultAccountLabel(user, !brokerage.usingBrokerage),
  });
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
    <div className="min-h-screen bg-ink text-champagne" data-testid="portfolio-page">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <ApexLogo size={36} className="shrink-0" />
          <p className="font-display text-xl tracking-[0.2em]">APEX</p>
          <Link to="/app" className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-gold hover:bg-gold/10" data-testid="desk-link">
            Dashboard
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <SettingsGearLink />
          <LogoutButton />
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        <div>
          <h1 className="font-display text-2xl">Portfolio</h1>
          <p className="mt-1 text-sm text-subtle" data-testid="portfolio-header-balance">
            {headerLabel} {fmtBalance(headerBalance)}
          </p>
          {usingBrokerage && brokerage.activeAccount && (
            <p className="mt-1 text-xs text-faint" data-testid="portfolio-brokerage-account">
              {brokerage.activeAccount.account_name} · {brokerage.activeAccount.broker_name}
            </p>
          )}
          {!usingBrokerage && (
            <p className="mt-1 text-xs text-faint" data-testid="portfolio-paper-context">
              Paper trading account
            </p>
          )}
        </div>

          {loadError && (
          <p className="apex-alert apex-alert-error" role="alert">
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
            <p className="mt-2 text-xs text-faint" data-testid="portfolio-chart-loading">
              Loading portfolio history…
            </p>
          )}
        </section>

        <Collapsible title="Current Portfolio" testId="portfolio-positions-section">
          <p className="mt-2 text-xs text-faint">
            {usingBrokerage
              ? "Open positions from your connected brokerage — read-only, synced with the dashboard."
              : "Open positions from your desk — same data as the dashboard table."}
          </p>
          {positionsLoading ? (
            <p className="mt-3 text-sm text-faint">Loading positions…</p>
          ) : openPositions.length === 0 ? (
            <p className="mt-3 text-sm text-faint">No open positions.</p>
          ) : (
            <div className="apex-table-wrap">
            <table className="apex-table mt-3" data-testid="portfolio-positions">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th className="apex-num">Qty</th>
                  <th className="apex-num">Avg cost</th>
                  <th className="apex-num">Current</th>
                  <th className="apex-num">Unrealized P&amp;L</th>
                  <th className="apex-num">Market value</th>
                  {!usingBrokerage && <th className="text-right">Action</th>}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p) => (
                  <tr
                    key={p.id}
                    className="cursor-pointer"
                    data-testid={`position-row-${p.id}`}
                    tabIndex={0}
                    role="button"
                    aria-label={`View certificate for ${p.symbol}`}
                    onClick={() => cert.openPosition(p)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        cert.openPosition(p);
                      }
                    }}
                  >
                    <td className="font-mono">{p.symbol}</td>
                    <td>{assetLabel(p.asset_class ?? "us_equity")}</td>
                    <td className="apex-num">{fmtPlain(p.qty)}</td>
                    <td className="apex-num">{fmtPlain(p.avg_cost)}</td>
                    <td className="apex-num">{fmtPlain(p.current)}</td>
                    <td className={`apex-num ${p.unrealized_pl >= 0 ? "num-up" : "num-down"}`}>{fmtMoney(p.unrealized_pl)}</td>
                    <td className="apex-num">{fmtMoney(p.market_value)}</td>
                    {!usingBrokerage && (
                      <td className="text-right">
                        <button
                          type="button"
                          className="rounded border border-line px-2 py-1 text-xs text-gold hover:bg-gold/10 disabled:opacity-40"
                          data-testid={`close-position-${p.id}`}
                          disabled={close.isPending}
                          onClick={(e) => {
                            e.stopPropagation();
                            close.mutate(p.id);
                          }}
                        >
                          Close
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </Collapsible>

        <Collapsible title="Order History" testId="portfolio-orders-section" defaultOpen={false}>
          {ordersLoading ? (
            <p className="mt-3 text-sm text-faint">Loading orders…</p>
          ) : orderRows.length === 0 ? (
            <p className="mt-3 text-sm text-faint">
              {usingBrokerage ? "No recent brokerage orders." : "No orders yet."}
            </p>
          ) : (
            <div className="apex-table-wrap">
            <table className="apex-table mt-3" data-testid="portfolio-orders">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Side</th>
                  <th>Symbol</th>
                  <th className="apex-num">Qty</th>
                  <th className="apex-num">Fill</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orderRows.map((o) => (
                  <tr key={o.id}>
                    <td className="text-subtle">{fmtTs(o.filled_at ?? o.created_at)}</td>
                    <td>{o.side.toUpperCase()}</td>
                    <td className="font-mono">{o.symbol}</td>
                    <td className="apex-num">{fmtPlain(o.qty)}</td>
                    <td className="apex-num">{fmtPlain(o.fill_price)}</td>
                    <td>{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </Collapsible>

        <Collapsible title="Overall P&amp;L" testId="portfolio-overall-section" defaultOpen={false}>
          {overallLoading ? (
            <p className="mt-3 text-sm text-faint">Loading P&amp;L breakdown…</p>
          ) : overallRows.length === 0 ? (
            <p className="mt-3 text-sm text-faint">No trade history yet.</p>
          ) : (
            <div className="apex-table-wrap">
            <table className="apex-table mt-3">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th className="apex-num">Qty</th>
                  <th className="apex-num">Realized</th>
                  <th className="apex-num">Unrealized</th>
                  <th className="apex-num">Total</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {overallRows.map((r) => (
                  <tr key={r.symbol}>
                    <td className="font-mono">{r.symbol}</td>
                    <td>{assetLabel(r.asset_class)}</td>
                    <td className="apex-num">{fmtPlain(r.qty)}</td>
                    <td className={`apex-num ${r.realized_pl >= 0 ? "num-up" : "num-down"}`}>{fmtMoney(r.realized_pl)}</td>
                    <td className={`apex-num ${r.unrealized_pl >= 0 ? "num-up" : "num-down"}`}>{fmtMoney(r.unrealized_pl)}</td>
                    <td className={`apex-num ${r.total_pl >= 0 ? "num-up" : "num-down"}`}>{fmtMoney(r.total_pl)}</td>
                    <td>{r.is_open ? "Open" : "Closed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </Collapsible>
      </main>

      {cert.selected ? (
        <PositionCertificateModal
          details={cert.selected}
          onDismiss={cert.dismiss}
          onClosePosition={!usingBrokerage ? (id) => close.mutate(id) : undefined}
          closing={close.isPending}
        />
      ) : null}

      <LegalFooter className="px-4 pb-6" />
    </div>
  );
}
