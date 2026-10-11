import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ApexWordmark } from "../components/ApexWordmark";
import { LegalFooter } from "../components/LegalFooter";
import { LogoutButton } from "../components/LogoutButton";
import { PositionCertificateModal } from "../components/PositionCertificateModal";
import { SettingsGearLink } from "../components/SettingsGearLink";
import { DailyPnlList, PositionDailyPnl } from "../components/DailyPnlList";
import { OverallPnlTotal } from "../components/OverallPnlTotal";
import { PnlChart } from "../components/PnlChart";
import { useAccountOverallPnl } from "../hooks/useAccountOverallPnl";
import { useBrokerage } from "../hooks/useBrokerage";
import { defaultAccountLabel, usePositionCertificate } from "../hooks/usePositionCertificate";
import { daysForPosition } from "../lib/dailyPnl";
import { DESK_STALE_MS, refreshDeskQueries } from "../lib/deskRefresh";
import { filterPnlPoints, type PnlTimeframe } from "../lib/pnlTimeframe";
import { assetLabel, fmtBalance, fmtMoney, fmtPlain, fmtTs } from "../lib/portfolioFormat";
import { isRiskProfile, patchUserSettings, readUserSettings, type RiskProfile } from "../lib/userSettings";
import { useSession } from "../store";
import { formatOptionExpiration, parseOccSymbol } from "../lib/optionSymbolParse";
import type { OrderHistoryRow, PositionRow } from "../types";

function Collapsible({
  title,
  testId,
  defaultOpen = true,
  footer,
  children,
}: {
  title: string;
  testId: string;
  defaultOpen?: boolean;
  footer?: React.ReactNode;
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
      {footer && <div className="border-t border-line px-4 py-3">{footer}</div>}
    </section>
  );
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
  const [riskProfile, setRiskProfile] = useState<RiskProfile>(() => readUserSettings().riskProfile);

  useEffect(() => {
    let cancelled = false;
    void api.getSettings().then((raw) => {
      if (cancelled || !raw || typeof raw !== "object") return;
      const profile = (raw as { risk_profile?: unknown }).risk_profile;
      if (!isRiskProfile(profile)) return;
      const next = patchUserSettings({ riskProfile: profile });
      setRiskProfile(next.riskProfile);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function onRiskProfileChange(nextProfile: RiskProfile) {
    const next = patchUserSettings({ riskProfile: nextProfile });
    setRiskProfile(next.riskProfile);
    void api.syncSettings(next);
  }

  const usingBrokerage = brokerage.usingBrokerage;

  const summary = useQuery({
    queryKey: ["port"],
    queryFn: () => api.portfolio(),
    enabled: !usingBrokerage,
    staleTime: DESK_STALE_MS,
  });
  const paperPnlHistory = useQuery({
    queryKey: ["pnl-history"],
    queryFn: () => api.pnlHistory(),
    enabled: !usingBrokerage,
    retry: 2,
    staleTime: DESK_STALE_MS,
  });
  const dailyPnl = useQuery({
    queryKey: ["daily-pnl"],
    queryFn: () => api.dailyPnl(),
    enabled: !usingBrokerage,
    retry: 2,
    staleTime: DESK_STALE_MS,
  });
  const brokerageEquityHistory = useQuery({
    queryKey: ["brokerage", "equity-history", brokerage.activeAccountId],
    queryFn: () => api.brokerageEquityHistory(brokerage.activeAccountId!),
    enabled: usingBrokerage && Boolean(brokerage.activeAccountId),
    retry: 2,
    staleTime: DESK_STALE_MS,
  });
  const accountPnl = useAccountOverallPnl();
  const positions = useQuery({
    queryKey: ["pos"],
    queryFn: () => api.positions(),
    enabled: !usingBrokerage,
    staleTime: DESK_STALE_MS,
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

  const cancelQueued = useMutation({
    mutationFn: (id: string) => api.cancelQueuedOrder(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["orders"] });
    },
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
      refreshDeskQueries(qc);
    },
  });

  const historyQuery = usingBrokerage ? brokerageEquityHistory : paperPnlHistory;
  const rawPoints = historyQuery.data?.points ?? [];
  const points = useMemo(() => filterPnlPoints(rawPoints, chartTimeframe), [rawPoints, chartTimeframe]);
  const fallbackBalance = usingBrokerage
    ? (historyQuery.data?.starting_balance ?? brokerage.stats?.portfolio_value ?? 0)
    : (historyQuery.data?.starting_balance ??
      summary.data?.starting_balance ??
      user?.starting_balance ??
      summary.data?.portfolio_value ??
      user?.portfolio_value ??
      0);
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
  const queuedRows = usingBrokerage
    ? []
    : orderRows.filter((row) => row.status === "queued" || row.status === "submitting" || row.status === "unknown");
  const historyRows = usingBrokerage
    ? orderRows
    : orderRows.filter((row) => row.status !== "queued" && row.status !== "submitting" && row.status !== "unknown");
  const historyOverall =
    usingBrokerage && rawPoints.length > 0 ? (rawPoints[rawPoints.length - 1]?.cumulative_pl ?? null) : null;
  const displayedOverall = usingBrokerage ? historyOverall : accountPnl.total;
  const ordersLoading = usingBrokerage ? brokerageOrders.isLoading : paperOrders.isLoading;
  const overallRows = accountPnl.rows;
  const overallLoading = accountPnl.loading;
  const totalPnl = displayedOverall;
  const loadError =
    summary.error?.message ??
    historyQuery.error?.message ??
    positions.error?.message ??
    (accountPnl.error instanceof Error ? accountPnl.error.message : null) ??
    paperOrders.error?.message ??
    brokerageOrders.error?.message ??
    null;

  return (
    <div className="min-h-screen bg-ink text-champagne" data-testid="portfolio-page">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <ApexWordmark />
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
          {usingBrokerage && (
            <p className="mt-1 text-sm" data-testid="portfolio-header-pnl">
              <span
                className={
                  brokerage.stats?.day_pnl == null
                    ? "text-faint"
                    : brokerage.stats.day_pnl > 0
                      ? "num-up"
                      : brokerage.stats.day_pnl < 0
                        ? "num-down"
                        : ""
                }
              >
                Daily P&amp;L{" "}
                {brokerage.stats?.day_pnl == null
                  ? "Unavailable"
                  : `${fmtMoney(brokerage.stats.day_pnl)}${
                      brokerage.balance?.day_pnl_percent != null ? ` (${brokerage.balance.day_pnl_percent.toFixed(2)}%)` : ""
                    }`}
              </span>
              <span className="text-faint"> · </span>
              <span className={totalPnl == null ? "text-faint" : totalPnl > 0 ? "num-up" : totalPnl < 0 ? "num-down" : ""}>
                Overall P&amp;L {fmtMoney(totalPnl)}
              </span>
            </p>
          )}
          {usingBrokerage && brokerage.activeAccount && (
            <p className="mt-1 text-xs text-faint" data-testid="portfolio-brokerage-account">
              {brokerage.activeAccount.account_name} · {brokerage.activeAccount.broker_name}
            </p>
          )}
          {usingBrokerage && (
            <p className="mt-1 text-xs text-bronze" data-testid="portfolio-read-only">
              Read-only. You can view this brokerage account, but you can’t place trades from APEX.
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
            headlineEquity={typeof headerBalance === "number" ? headerBalance : undefined}
            timeframe={chartTimeframe}
            onTimeframeChange={setChartTimeframe}
            valueLabel={usingBrokerage ? "Equity" : "Portfolio value"}
            pending={historyQuery.isFetching && !historyQuery.data}
            overallTotal={totalPnl}
            emptyLabel={rawPoints.length > 0 ? "No portfolio history in this range." : "No equity history yet."}
          />
          {historyQuery.data?.history_note && (
            <p className="mt-2 text-xs text-faint" data-testid="portfolio-history-note">
              {historyQuery.data.history_note}
            </p>
          )}
          {usingBrokerage && (
            <div className="mt-3 rounded-xl border border-line bg-panel px-4 py-3" data-testid="brokerage-daily-pnl">
              <p className="text-[10px] uppercase tracking-wider text-bronze">Daily P&amp;L</p>
              <p
                className={`mt-1 font-mono text-sm ${
                  brokerage.stats?.day_pnl == null
                    ? "text-faint"
                    : brokerage.stats.day_pnl > 0
                      ? "num-up"
                      : brokerage.stats.day_pnl < 0
                        ? "num-down"
                        : "text-champagne"
                }`}
                data-testid="brokerage-daily-pnl-value"
              >
                {brokerage.balance == null
                  ? "Loading…"
                  : brokerage.stats?.day_pnl == null
                    ? "Unavailable"
                    : fmtMoney(brokerage.stats.day_pnl)}
              </p>
              <p className="mt-1 text-xs text-faint">
                {brokerage.balance?.day_pnl_note ||
                  "SnapTrade’s 1-day account return, in dollars of current equity. This is not Overall P&L."}
                {brokerage.balance?.as_of_timestamp ? ` As of ${fmtTs(brokerage.balance.as_of_timestamp)} local time.` : ""}
              </p>
            </div>
          )}
          {!usingBrokerage && dailyPnl.data && dailyPnl.data.book.length > 0 && (
            <div className="mt-3 rounded-xl border border-line bg-panel px-4 py-3" data-testid="book-daily-pnl">
              <p className="text-[10px] uppercase tracking-wider text-bronze">Book daily P&L</p>
              <DailyPnlList days={dailyPnl.data.book} testId="book-daily-pnl-list" />
            </div>
          )}
          {!usingBrokerage && dailyPnl.isError && (
            <p className="mt-2 text-xs text-faint" data-testid="daily-pnl-error">
              Daily P&L unavailable
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
                {openPositions.map((p) => {
                  const seriesDays = usingBrokerage ? undefined : daysForPosition(dailyPnl.data, p.id);
                  return (
                  <Fragment key={p.id}>
                  <tr
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
                  {seriesDays && seriesDays.length > 0 && (
                    <tr data-testid={`position-daily-row-${p.id}`}>
                      <td colSpan={usingBrokerage ? 7 : 8} className="px-2 pb-3">
                        <PositionDailyPnl symbol={p.symbol} days={seriesDays} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </Collapsible>

        <Collapsible title="Queued" testId="portfolio-queued-section" defaultOpen>
          {ordersLoading ? (
            <p className="mt-3 text-sm text-faint">Loading queued orders…</p>
          ) : queuedRows.length === 0 ? (
            <p className="mt-3 text-sm text-faint" data-testid="queued-empty">
              No orders are waiting for a price.
            </p>
          ) : (
            <div className="apex-table-wrap">
              <table className="apex-table mt-3" data-testid="portfolio-queued">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Strategy</th>
                    <th>Symbol</th>
                    <th className="apex-num">Qty</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {queuedRows.map((o) => (
                    <tr key={o.id} data-testid={`queued-row-${o.id}`}>
                      <td className="text-subtle">{fmtTs(o.created_at)}</td>
                      <td>{o.strategy_name || "—"}</td>
                      <td className="font-mono">{o.symbol}</td>
                      <td className="apex-num">{fmtPlain(o.qty)}</td>
                      <td>
                        Queued
                        {o.queue_reason ? <p className="text-xs text-faint">{o.queue_reason}</p> : null}
                      </td>
                      <td>
                        {o.status === "queued" ? (
                          <button
                            type="button"
                            className="text-gold"
                            data-testid={`cancel-queued-${o.id}`}
                            disabled={cancelQueued.isPending}
                            onClick={() => cancelQueued.mutate(o.id)}
                          >
                            Cancel
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Collapsible>

        <Collapsible
          key={usingBrokerage ? "broker-orders" : "paper-orders"}
          title="Order History"
          testId="portfolio-orders-section"
          defaultOpen={usingBrokerage}
        >
          {ordersLoading ? (
            <p className="mt-3 text-sm text-faint">Loading orders…</p>
          ) : historyRows.length === 0 ? (
            <p className="mt-3 text-sm text-faint">
              {usingBrokerage ? "No brokerage orders in the available history." : "No orders yet."}
            </p>
          ) : (
            <div className="apex-table-wrap">
            {usingBrokerage && (
              <p className="mt-3 text-xs text-faint" data-testid="brokerage-orders-note">
                {brokerageOrders.data?.history_note ||
                  "Broker order records cover the last 90 days. Times are shown in your local timezone."}
              </p>
            )}
            <table className="apex-table mt-3" data-testid="portfolio-orders">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Side</th>
                  <th>Symbol</th>
                  <th>Strike</th>
                  <th>Expiry</th>
                  <th className="apex-num">Qty</th>
                  <th>Type</th>
                  <th className="apex-num">Limit</th>
                  <th className="apex-num">Fill</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {historyRows.map((o) => {
                  const parsed = parseOccSymbol(o.symbol);
                  const qtyLabel =
                    o.filled_qty != null && o.filled_qty !== o.qty
                      ? `${fmtPlain(o.filled_qty)} / ${fmtPlain(o.qty)}`
                      : fmtPlain(o.qty);
                  return (
                    <tr key={o.id}>
                      <td className="text-subtle">{fmtTs(o.filled_at ?? o.created_at)}</td>
                      <td>{o.side.toUpperCase()}</td>
                      <td className="font-mono">
                        {o.symbol}
                        {o.group_id ? <p className="text-xs text-faint">Leg group {o.group_id}</p> : null}
                        {o.source === "activity" ? <p className="text-xs text-faint">Account activity</p> : null}
                      </td>
                      <td>{parsed ? parsed.strike : "—"}</td>
                      <td>{parsed ? formatOptionExpiration(parsed.expiry) : "—"}</td>
                      <td className="apex-num">{qtyLabel}</td>
                      <td>{o.order_type || "market"}</td>
                      <td className="apex-num">{fmtPlain(o.limit_price)}</td>
                      <td className="apex-num">{fmtPlain(o.fill_price)}</td>
                      <td>{o.status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </Collapsible>

        <section className="rounded-xl border border-line bg-panel p-4" data-testid="portfolio-risk-profile">
          <label className="block text-sm">
            <span className="text-subtle">Risk profile</span>
            <select
              className="mt-1 w-full max-w-xs rounded-md border border-line bg-ink px-3 py-2 text-sm"
              data-testid="portfolio-risk-profile-select"
              value={riskProfile}
              onChange={(e) => onRiskProfileChange(e.target.value as RiskProfile)}
            >
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="aggressive">Aggressive</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <p className="mt-2 text-xs text-faint">Same profile as Settings → Risk &amp; Auto-Execution. Scans use this Best Match preference.</p>
        </section>

        <Collapsible
          title="Overall P&amp;L"
          testId="portfolio-overall-section"
          defaultOpen={false}
          footer={<OverallPnlTotal value={totalPnl} />}
        >
          {usingBrokerage && (
            <p className="mt-3 text-xs text-faint" data-testid="brokerage-overall-note">
              Overall P&amp;L matches the chart: account value change since the first available day, after deposits and withdrawals.
              Open-position rows below are unrealized only.
            </p>
          )}
          {overallLoading ? (
            <p className="mt-3 text-sm text-faint">Loading P&amp;L breakdown…</p>
          ) : overallRows.length === 0 ? (
            <p className="mt-3 text-sm text-faint">No order history yet.</p>
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
