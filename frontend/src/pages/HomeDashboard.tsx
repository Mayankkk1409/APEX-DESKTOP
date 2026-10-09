import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ApexLogo } from "../components/ApexLogo";
import { LogoutButton } from "../components/LogoutButton";
import { SettingsGearLink } from "../components/SettingsGearLink";
import type { BrokerageBalance } from "../lib/brokerageApi";
import { useSession } from "../store";

/** Names taken from the symbol catalog. This is a featured list, not a popularity ranking. */
const FEATURED = [
  { symbol: "SPX", name: "S&P 500 Index" },
  { symbol: "AAPL", name: "Apple Inc." },
  { symbol: "MSFT", name: "Microsoft Corporation" },
  { symbol: "NVDA", name: "NVIDIA Corporation" },
  { symbol: "QQQ", name: "Invesco QQQ Trust" },
  { symbol: "IWM", name: "iShares Russell 2000 ETF" },
] as const;

function money(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function HomeDashboard() {
  const nav = useNavigate();
  const setSymbol = useSession((s) => s.setSymbol);
  const user = useSession((s) => s.user);
  const watch = useQuery({ queryKey: ["watch"], queryFn: () => api.watchlist() });
  const accounts = useQuery({
    queryKey: ["brokerage", "accounts"],
    queryFn: () => api.brokerageAccounts() as Promise<{ connection_status: string | null; accounts: { id: string }[] }>,
  });
  const activeBrokerId = accounts.data?.accounts?.[0]?.id ?? null;
  const brokerBook = useQuery({
    queryKey: ["brokerage", "balance", activeBrokerId],
    queryFn: () => api.brokerageBalance(activeBrokerId!) as Promise<BrokerageBalance>,
    enabled: Boolean(activeBrokerId),
  });
  const paper = useQuery({ queryKey: ["port"], queryFn: () => api.portfolio() });
  const session = useQuery({ queryKey: ["market-session"], queryFn: () => api.marketSession(), staleTime: 30_000 });
  const scans = useQuery({ queryKey: ["scans-recent"], queryFn: () => api.recentScans() });

  function openDesk(symbol: string) {
    setSymbol(symbol);
    nav("/app");
  }

  const paperMode = user?.account_mode !== "real_brokerage";
  const brokerConnected = (accounts.data?.accounts?.length ?? 0) > 0 || accounts.data?.connection_status === "connected";
  const brokerBalance = brokerBook.data;

  return (
    <div className="min-h-screen bg-ink text-champagne" data-testid="home-dashboard">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <Link to="/dashboard" className="desk-brand" aria-label="Apex" data-testid="home-brand">
          <ApexLogo size={36} className="shrink-0" />
          <span className="font-display text-xl tracking-[0.2em]">APEX</span>
        </Link>
        <div className="flex items-center gap-2">
          <SettingsGearLink />
          <LogoutButton />
        </div>
      </header>
      <main className="mx-auto grid max-w-6xl gap-4 p-4 md:grid-cols-2">
        <section className="rounded-xl border border-line bg-panel p-4" data-testid="home-market">
          <h2 className="text-sm uppercase tracking-widest text-bronze">Market</h2>
          <p className="mt-2 text-lg" data-testid="home-market-phase">
            {session.data?.phase ?? "—"}
          </p>
          <p className="text-sm text-faint">
            {session.data ? (session.data.trading_day ? "Trading day" : "Not a trading day") : "—"}
            {session.data?.timezone ? ` · ${session.data.timezone}` : ""}
          </p>
        </section>

        <section className="rounded-xl border border-line bg-panel p-4" data-testid="home-accounts">
          <h2 className="text-sm uppercase tracking-widest text-bronze">Accounts</h2>
          {paperMode ? (
            <div className="mt-3" data-testid="home-paper">
              <p className="text-xs uppercase tracking-wider text-faint">Paper</p>
              <dl className="mt-1 space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt>Cash</dt>
                  <dd className="apex-num">{money(paper.data?.balance)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Buying power</dt>
                  <dd className="apex-num">{money(paper.data?.buying_power)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Portfolio</dt>
                  <dd className="apex-num">{money(paper.data?.portfolio_value)}</dd>
                </div>
              </dl>
            </div>
          ) : null}
          <div className="mt-3" data-testid="home-brokerage">
            <p className="text-xs uppercase tracking-wider text-faint">Brokerage · read only</p>
            {brokerConnected && brokerBalance ? (
              <dl className="mt-1 space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt>Cash</dt>
                  <dd className="apex-num">{money(brokerBalance.cash_balance)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Buying power</dt>
                  <dd className="apex-num">{money(brokerBalance.buying_power)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Equity</dt>
                  <dd className="apex-num">{money(brokerBalance.total_equity)}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-1 text-sm text-faint">{accounts.isFetched ? (brokerConnected ? "—" : "Not connected") : "—"}</p>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-line bg-panel p-4" data-testid="home-watchlist">
          <h2 className="text-sm uppercase tracking-widest text-bronze">Watchlist</h2>
          <ul className="mt-2 divide-y divide-line">
            {(watch.data?.items ?? []).map((item) => (
              <li key={item.symbol}>
                <button type="button" className="w-full py-2 text-left text-sm hover:text-gold" onClick={() => openDesk(item.symbol)}>
                  {item.symbol}
                </button>
              </li>
            ))}
          </ul>
          {watch.isFetched && (watch.data?.items ?? []).length === 0 ? <p className="mt-2 text-sm text-faint">No symbols yet</p> : null}
        </section>

        <section className="rounded-xl border border-line bg-panel p-4" data-testid="home-featured">
          <h2 className="text-sm uppercase tracking-widest text-bronze">Featured</h2>
          <ul className="mt-2 divide-y divide-line">
            {FEATURED.map((item) => (
              <li key={item.symbol}>
                <button type="button" className="flex w-full justify-between py-2 text-left text-sm hover:text-gold" onClick={() => openDesk(item.symbol)}>
                  <span>{item.symbol}</span>
                  <span className="text-faint">{item.name}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-line bg-panel p-4 md:col-span-2" data-testid="home-scans">
          <h2 className="text-sm uppercase tracking-widest text-bronze">Recent scans</h2>
          <ul className="mt-2 divide-y divide-line">
            {(scans.data?.scans ?? []).map((scan) => (
              <li key={scan.id}>
                <button
                  type="button"
                  className="flex w-full justify-between py-2 text-left text-sm hover:text-gold"
                  onClick={() => {
                    setSymbol(scan.symbol);
                    nav("/scan", { state: { reopenScanId: scan.id } });
                  }}
                >
                  <span>{scan.symbol}</span>
                  <span className="apex-num">{typeof scan.composite_score === "number" ? scan.composite_score : "—"}</span>
                </button>
              </li>
            ))}
          </ul>
          {scans.isFetched && (scans.data?.scans ?? []).length === 0 ? <p className="mt-2 text-sm text-faint">No scans yet</p> : null}
        </section>
      </main>
    </div>
  );
}
