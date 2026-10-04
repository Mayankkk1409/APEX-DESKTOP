import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, getAccessToken } from "../api";
import { BrokerageConnectionPanel } from "../components/BrokerageConnectionPanel";
import { LogoutButton } from "../components/LogoutButton";
import { PositionCertificateModal } from "../components/PositionCertificateModal";
import { SettingsGearLink } from "../components/SettingsGearLink";
import { TradingViewChart } from "../components/TradingViewChart";
import { ApexLogo } from "../components/ApexLogo";
import { LegalFooter } from "../components/LegalFooter";
import { WatchlistToggle } from "../components/WatchlistToggle";
import { captureChartState, getChartState, subscribeChartState } from "../chartCapture";
import { DEFAULT_SYMBOL, SNAPSHOT_STUDIES, WS_BASE } from "../constants";
import { useBrokerage } from "../hooks/useBrokerage";
import { defaultAccountLabel, usePositionCertificate } from "../hooks/usePositionCertificate";
import { resolvePositionDayPl } from "../lib/positionDayPl";
import { useSession } from "../store";
import type { Fundamentals, PositionRow, Quote, SentimentRow, WatchItem } from "../types";

export function Dashboard() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { user, setUser, showConnectModal, setConnectModal, symbol, setSymbol, timeframe, setTimeframe, expiry, setExpiry, captureSnapshot } =
    useSession();
  const chartState = useSyncExternalStore(subscribeChartState, getChartState, getChartState);
  const chartMatchesIntent = chartState.symbol === symbol && chartState.allBars.length > 0;
  const activeSymbol = chartMatchesIntent ? chartState.symbol : symbol;
  const chartReady = chartMatchesIntent;
  const [query, setQuery] = useState(symbol);
  const [hits, setHits] = useState<{ symbol: string; name: string }[]>([]);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  // The query the current hits belong to, so Enter never applies a suggestion
  // left over from the previously typed ticker.
  const [hitsFor, setHitsFor] = useState("");
  const searchSeq = useRef(0);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (chartReady) setQuery(activeSymbol);
  }, [activeSymbol, chartReady]);

  useEffect(() => {
    if (!chartReady) setQuery(symbol);
  }, [symbol, chartReady]);

  useEffect(() => {
    setHighlightIdx(-1);
  }, [hits]);

  function closeSuggestions() {
    searchSeq.current += 1;
    setHits([]);
    setHitsFor("");
    setHighlightIdx(-1);
    setSuggestionsOpen(false);
  }

  function applyTicker(next: string) {
    const s = next.trim().toUpperCase();
    if (!s) return;
    closeSuggestions();
    setSymbol(s);
    setQuery(s);
    setExpiry("");
    searchInputRef.current?.blur();
  }

  async function runSearch(value: string) {
    const seq = ++searchSeq.current;
    if (!value.trim()) {
      setHits([]);
      setHitsFor("");
      setSuggestionsOpen(false);
      return;
    }
    const r = await api.search(value);
    if (seq !== searchSeq.current) return;
    setHits(r.hits);
    setHitsFor(value);
    setSuggestionsOpen(r.hits.length > 0);
  }

  /** Enter resolves to an exact match, then a suggestion for this exact query, then the raw text. */
  function resolveTyped(): string {
    const typed = query.trim().toUpperCase();
    const exact = hits.find((h) => h.symbol.toUpperCase() === typed);
    if (exact) return exact.symbol;
    if (hitsFor.trim().toUpperCase() === typed && hits[0]) return hits[0].symbol;
    return typed;
  }
  const [watchOpen, setWatchOpen] = useState(true);
  const [sentOpen, setSentOpen] = useState(true);
  const [posOpen, setPosOpen] = useState(true);
  const [live, setLive] = useState<{ balance?: number; buying_power?: number; portfolio_value?: number }>({});
  const [scanning, setScanning] = useState(false);

  const quote = useQuery({
    queryKey: ["quote", activeSymbol],
    queryFn: () => api.quote(activeSymbol),
    staleTime: 5_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchInterval: 10_000,
    enabled: Boolean(activeSymbol),
  });
  const fundamentals = useQuery({
    queryKey: ["fundamentals", activeSymbol],
    queryFn: () => api.fundamentals(activeSymbol),
    staleTime: 15_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchInterval: 30_000,
    enabled: Boolean(activeSymbol),
  });
  const expiries = useQuery({
    queryKey: ["exp", activeSymbol],
    queryFn: () => api.expirations(activeSymbol),
    enabled: Boolean(activeSymbol),
  });
  const watch = useQuery({ queryKey: ["watch"], queryFn: () => api.watchlist() });
  const sentiment = useQuery({
    queryKey: ["sent", activeSymbol],
    queryFn: () => api.sentiment(activeSymbol),
    enabled: Boolean(activeSymbol),
  });
  const brokerage = useBrokerage();
  const cert = usePositionCertificate({
    isPaper: !brokerage.usingBrokerage,
    accountLabel: defaultAccountLabel(user, !brokerage.usingBrokerage),
  });
  const portfolio = useQuery({ queryKey: ["port"], queryFn: () => api.portfolio(), enabled: !brokerage.usingBrokerage });
  const positions = useQuery({ queryKey: ["pos"], queryFn: () => api.positions(), enabled: !brokerage.usingBrokerage });
  // Keep the picker on a live expiry for the current underlying. On symbol change
  // applyTicker clears expiry; once the refetch lands, default to the nearest date.
  useEffect(() => {
    const list = expiries.data?.expirations ?? [];
    if (!list.length) return;
    if (!expiry || !list.some((ex) => ex.date === expiry)) {
      setExpiry(list[0].date);
    }
  }, [expiries.data, expiry, setExpiry]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    let ws: WebSocket | null = null;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      ws = new WebSocket(`${WS_BASE}/ws/market?token=${token}`);
      ws.onopen = () => ws?.send(JSON.stringify({ type: "subscribe", symbols: [activeSymbol, DEFAULT_SYMBOL] }));
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "fill") {
          setLive({ balance: msg.balance, buying_power: msg.buying_power, portfolio_value: msg.portfolio_value });
          qc.invalidateQueries({ queryKey: ["port"] });
          qc.invalidateQueries({ queryKey: ["pos"] });
          qc.invalidateQueries({ queryKey: ["orders"] });
        }
        if (msg.type === "quotes") {
          for (const row of (msg.quotes as Quote[]) ?? []) {
            if (row.symbol !== activeSymbol || row.price == null) continue;
            qc.setQueryData<Quote>(["quote", activeSymbol], (old) =>
              old ? { ...old, ...row, price: row.price, change: row.change, change_pct: row.change_pct } : row,
            );
          }
        }
      };
      ws.onclose = () => {
        if (!stopped) setTimeout(connect, 800);
      };
    };
    connect();
    return () => {
      stopped = true;
      ws?.close();
    };
  }, [qc, activeSymbol]);

  const stats = brokerage.usingBrokerage && brokerage.stats
    ? {
        balance: brokerage.stats.balance,
        buying_power: brokerage.stats.buying_power,
        portfolio_value: brokerage.stats.portfolio_value,
      }
    : {
        balance: live.balance ?? portfolio.data?.balance ?? user?.cash_balance ?? 0,
        buying_power: live.buying_power ?? portfolio.data?.buying_power ?? user?.buying_power ?? 0,
        portfolio_value: live.portfolio_value ?? portfolio.data?.portfolio_value ?? user?.portfolio_value ?? 0,
      };

  const displayPositions: PositionRow[] = brokerage.usingBrokerage
    ? brokerage.positionRows
    : ((positions.data?.positions as PositionRow[]) ?? []);
  const positionsLoading = brokerage.usingBrokerage ? brokerage.positionsQuery.isLoading : positions.isLoading;
  const positionSymbols = useMemo(
    () => [...new Set(displayPositions.map((p) => p.symbol))],
    [displayPositions],
  );
  const positionQuoteQueries = useQueries({
    queries: positionSymbols.map((sym) => ({
      queryKey: ["quote", sym],
      queryFn: () => api.quote(sym),
      staleTime: 5_000,
      enabled: displayPositions.length > 0,
    })),
  });
  const quoteBySymbol = useMemo(() => {
    const map = new Map<string, Quote>();
    positionSymbols.forEach((sym, i) => {
      const row = positionQuoteQueries[i]?.data;
      if (row) map.set(sym, row);
    });
    return map;
  }, [positionSymbols, positionQuoteQueries]);
  const dayPl = brokerage.usingBrokerage
    ? (brokerage.stats?.day_pnl ?? null)
    : (portfolio.data?.day_pl as number | null | undefined);
  const dayPct = brokerage.usingBrokerage
    ? brokerage.stats?.day_pnl != null && brokerage.stats.portfolio_value
      ? (brokerage.stats.day_pnl / brokerage.stats.portfolio_value) * 100
      : null
    : Number(portfolio.data?.day_pct ?? 0);

  const later = useMutation({
    mutationFn: () => api.brokerage(true),
    onSuccess: (u) => {
      setUser(u as typeof user);
      setConnectModal(false);
    },
  });
  const now = useMutation({
    mutationFn: () => api.brokerage(false),
    onSuccess: (u) => {
      setUser(u as typeof user);
      setConnectModal(false);
    },
  });

  /**
   * Freeze exactly what is on screen: same symbol, same interval, and the bars
   * inside the visible range. Deep Scan computes every number from this window.
   */
  function scan() {
    if (scanning) return;
    setScanning(true);
    const captured = captureChartState();
    const chartSymbol = captured.symbol && captured.visibleBars.length > 0 ? captured.symbol : activeSymbol;
    const usable =
      captured.symbol === chartSymbol &&
      captured.timeframe === timeframe &&
      captured.visibleBars.length > 0;
    const nowIso = captured.capturedAt || new Date().toISOString();
    captureSnapshot(
      {
        symbol: chartSymbol,
        timeframe,
        visible_from: usable ? captured.from : "",
        visible_to: usable ? captured.to : "",
        studies: captured.studies.length ? captured.studies : SNAPSHOT_STUDIES,
        captured_at: nowIso,
      },
      captured.png,
      Boolean(captured.png),
      usable ? captured.visibleBars : [],
      usable ? captured.allBars : [],
      usable ? captured.dailyBars : [],
    );
    nav("/scan");
    setScanning(false);
  }

  const qRaw = quote.data;
  const q =
    qRaw?.symbol?.toUpperCase() === activeSymbol.toUpperCase() ? qRaw : undefined;
  const fRaw = fundamentals.data as Fundamentals | undefined;
  const f = fRaw && chartReady ? fRaw : undefined;
  const change = q?.change ?? null;
  const changeCls = change == null ? "text-faint" : change >= 0 ? "num-up" : "num-down";
  const quoteStatus = q?.status ?? (quote.isError ? "unavailable" : undefined);
  const liveName = q?.name || (activeSymbol === DEFAULT_SYMBOL ? "S&P 500 INDEX" : activeSymbol);
  const avgVolume = f?.avg_volume ?? q?.avg_volume;
  const marketCap = f?.market_cap ?? q?.market_cap;
  const peTtm = f?.pe_ttm ?? q?.pe_ttm;
  const divYield = f?.div_yield ?? q?.div_yield;
  const expenseRatio = f?.expense_ratio ?? q?.expense_ratio;
  const beta5y = f?.beta_5y ?? q?.beta_5y;

  return (
    <div className="min-h-screen" data-testid="dashboard">
      {user?.connect_later_banner && (
        <div className="flex items-center justify-between border-b border-line bg-gold/10 px-4 py-2 text-sm" data-testid="connect-banner">
          <span>Brokerage not connected — paper/demo data is active. Connect anytime.</span>
          <button className="text-gold" onClick={() => api.dismissBanner().then((u) => setUser(u as typeof user))}>
            Dismiss
          </button>
        </div>
      )}
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
        <ApexLogo size={36} className="shrink-0" />
        <p className="font-display text-xl tracking-[0.2em]">APEX</p>
        <div className="relative">
          <input
            ref={searchInputRef}
            data-testid="ticker-search"
            className="w-56 rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
            value={query}
            placeholder="Search ticker"
            autoComplete="off"
            role="combobox"
            aria-expanded={suggestionsOpen}
            aria-controls="ticker-suggestions"
            aria-activedescendant={highlightIdx >= 0 ? `ticker-hit-${highlightIdx}` : undefined}
            onChange={(e) => {
              setQuery(e.target.value);
              void runSearch(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                if (!hits.length) return;
                e.preventDefault();
                setHighlightIdx((i) => (i < hits.length - 1 ? i + 1 : 0));
                return;
              }
              if (e.key === "ArrowUp") {
                if (!hits.length) return;
                e.preventDefault();
                setHighlightIdx((i) => (i > 0 ? i - 1 : hits.length - 1));
                return;
              }
              if (e.key === "Escape") {
                closeSuggestions();
                return;
              }
              if (e.key !== "Enter") return;
              e.preventDefault();
              if (highlightIdx >= 0 && hits[highlightIdx]) {
                applyTicker(hits[highlightIdx].symbol);
              } else {
                applyTicker(resolveTyped());
              }
            }}
          />
          {suggestionsOpen && hits.length > 0 && (
            <ul id="ticker-suggestions" className="absolute z-20 mt-1 w-full rounded-md border border-line bg-panel text-sm" role="listbox">
              {hits.map((h, i) => (
                <li key={h.symbol} id={`ticker-hit-${i}`} role="option" aria-selected={i === highlightIdx}>
                  <button
                    type="button"
                    className={`w-full px-3 py-1 text-left ${i === highlightIdx ? "bg-gold/20" : "hover:bg-gold/10"}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      applyTicker(h.symbol);
                    }}
                  >
                    {h.symbol} — {h.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <WatchlistToggle symbol={activeSymbol} testid="watchlist-toggle" />
        <select
          data-testid="expiry"
          className="rounded-md border border-line bg-panel px-2 py-1.5 text-sm"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          data-expiry-count={(expiries.data?.expirations ?? []).length}
          title={
            (expiries.data?.expirations ?? []).length
              ? `${(expiries.data?.expirations ?? []).length} listed expirations`
              : "No listed expirations for this underlying"
          }
        >
          {(expiries.data?.expirations ?? []).map((ex) => (
            <option key={ex.date} value={ex.date}>
              {ex.date} ({ex.dte}d · {ex.kind}
              {ex.near_expiry ? " · near" : ""})
            </option>
          ))}
        </select>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            to="/portfolio"
            className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-gold hover:bg-gold/10"
            data-testid="portfolio-btn"
          >
            Portfolio
          </Link>
          <SettingsGearLink />
          <LogoutButton />
        </div>
      </header>

      <section className="grid grid-cols-3 gap-3 px-4 py-3">
        <Stat label="Balance" value={stats.balance} testid="stat-balance" />
        <Stat label="Buying Power" value={stats.buying_power} testid="stat-bp" />
        <Stat label="Portfolio Value" value={stats.portfolio_value} testid="stat-pv" />
      </section>

      <div className="grid grid-cols-12 items-stretch gap-3 px-4 pb-3">
        <aside
          className="col-span-12 h-[calc(100dvh-10.75rem)] min-h-[36rem] overflow-auto rounded-xl border border-line bg-panel p-4 lg:col-span-2"
          data-testid="ticker-panel"
        >
          <p className="font-display text-2xl">{activeSymbol}</p>
          <p className="text-xs text-bronze">{liveName}</p>
          {!chartReady || (quote.isLoading && !q) ? (
            <p className="mt-2 text-sm text-faint" data-testid="quote-loading">
              Loading live quote…
            </p>
          ) : quoteStatus === "unavailable" || quote.isError ? (
            <div className="mt-2" data-testid="quote-unavailable">
              <p className="font-mono text-3xl text-faint">—</p>
              <p className="mt-1 text-xs text-subtle">Live data unavailable. No placeholder values shown.</p>
            </div>
          ) : (
            <>
              <p className="mt-2 font-mono text-3xl" data-testid="quote-price">
                {fmt(q?.price)}
              </p>
              <p className={`font-mono ${changeCls}`} data-testid="quote-change">
                {fmtSigned(change)} ({fmtPct(q?.change_pct)})
              </p>
            </>
          )}
          <dl className="mt-4 space-y-1 text-sm">
            <Row k="Open" v={fmt(q?.open)} />
            <Row k="High" v={fmt(q?.high)} />
            <Row k="Low" v={fmt(q?.low)} />
            <Row k="Volume" v={n(q?.volume)} />
            <Row k="Avg Volume" v={n(avgVolume)} />
            <Row k="52W High" v={fmt(q?.week_52_high)} />
            <Row k="52W Low" v={fmt(q?.week_52_low)} />
            <Row k="Market Cap" v={marketCap ? n(marketCap) : "—"} />
            <Row k="P/E (TTM)" v={peTtm != null ? Number(peTtm).toFixed(2) : "—"} />
            <Row k="Div Yield" v={divYield != null ? `${(divYield * 100).toFixed(2)}%` : "—"} />
            <Row k="Expense Ratio" v={expenseRatio != null ? `${(expenseRatio * 100).toFixed(3)}%` : "—"} />
            <Row k="Beta (5Y)" v={beta5y != null ? Number(beta5y).toFixed(2) : "—"} />
          </dl>
          <p className="mt-3 text-[10px] text-faint" data-testid="quote-source">
            {quoteSourceLabel(q?.source, q?.secondary_source, f?.source)}
          </p>
          {q?.as_of && (
            <p className="text-[10px] text-faint" data-testid="quote-asof">
              As of {q.as_of}
            </p>
          )}
        </aside>

        <section className="col-span-12 flex flex-col gap-3 lg:col-span-10">
          <div className="h-[calc(100dvh-9.5rem)] min-h-[42rem]">
            <TradingViewChart symbol={symbol} timeframe={timeframe} onTimeframeChange={setTimeframe} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-panel px-4 py-2.5">
            <div>
              <p className="text-xs uppercase tracking-wider text-bronze">Daily portfolio summary</p>
              <p className="font-mono" data-testid="day-pl-summary">
                Day P&L {fmt(dayPl)} · {dayPl == null || dayPct == null ? "—" : `${dayPct.toFixed(2)}%`}
              </p>
              <p className="text-xs text-faint">
                Top movers: {((portfolio.data?.top_movers as { symbol: string }[]) ?? []).map((m) => m.symbol).join(", ") || "—"}
              </p>
            </div>
            <button data-testid="scan-btn" disabled={scanning || !chartReady} onClick={() => void scan()} className="rounded-md bg-gold px-5 py-2 font-medium text-ink disabled:opacity-40">
              Scan {activeSymbol}
            </button>
          </div>
        </section>
      </div>

      <section className="space-y-3 px-4 pb-10" data-testid="desk-drawer">
        <BrokerageConnectionPanel />
        <div className="rounded-xl border border-line bg-panel">
          <button
            type="button"
            className="flex w-full items-center justify-between px-4 py-3 text-sm text-gold"
            data-testid="pos-toggle"
            aria-expanded={posOpen}
            onClick={() => setPosOpen((v) => !v)}
          >
            Open positions <span aria-hidden>{posOpen ? "▾" : "▸"}</span>
          </button>
          {posOpen && (
            <div className="apex-table-wrap border-t border-line">
            <table className="apex-table" data-testid="positions">
              <thead>
                <tr>
                  <th className="px-4">Symbol</th>
                  <th className="apex-num">Qty</th>
                  <th className="apex-num">Avg cost</th>
                  <th className="apex-num">Current</th>
                  <th className="apex-num">Daily P/L</th>
                  <th className="apex-num">Unrealized P&L</th>
                  <th className="apex-num px-4">Market value</th>
                </tr>
              </thead>
              <tbody>
                {positionsLoading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-3 text-faint">
                      Loading positions…
                    </td>
                  </tr>
                ) : displayPositions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-3 text-faint">
                      No open positions.
                    </td>
                  </tr>
                ) : (
                  displayPositions.map((p) => {
                    const positionDayPl = resolvePositionDayPl(p, quoteBySymbol.get(p.symbol));
                    return (
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
                      <td className="px-4 font-mono">{p.symbol}</td>
                      <td className="apex-num">{p.qty}</td>
                      <td className="apex-num">{fmt(p.avg_cost)}</td>
                      <td className="apex-num">{fmt(p.current)}</td>
                      <td className={`apex-num ${positionDayPl == null ? "text-faint" : positionDayPl >= 0 ? "num-up" : "num-down"}`}>
                        {fmt(positionDayPl)}
                      </td>
                      <td className={`apex-num ${p.unrealized_pl >= 0 ? "num-up" : "num-down"}`}>{fmt(p.unrealized_pl)}</td>
                      <td className="apex-num px-4">{fmt(p.market_value)}</td>
                    </tr>
                    );
                  })
                )}
              </tbody>
            </table>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="desk-aux">
          <div className="rounded-xl border border-line bg-panel">
            <button
              type="button"
              className="flex w-full items-center justify-between px-4 py-3 text-sm"
              data-testid="watch-toggle"
              aria-expanded={watchOpen}
              onClick={() => setWatchOpen((v) => !v)}
            >
              Watchlist <span aria-hidden>{watchOpen ? "▾" : "▸"}</span>
            </button>
            {watchOpen && (
              <ul className="border-t border-line px-3 py-2 text-sm" data-testid="watch-list">
                {((watch.data?.items as WatchItem[]) ?? []).length === 0 ? (
                  <li className="py-2 text-faint" data-testid="watch-empty">
                    Watchlist is empty — search a ticker and add it.
                  </li>
                ) : (
                  ((watch.data?.items as WatchItem[]) ?? []).map((w) => (
                    <li key={w.symbol} className="flex justify-between py-1">
                      <button className="text-left" onClick={() => applyTicker(w.symbol)}>
                        {w.symbol}
                      </button>
                      <span className={w.change_pct == null ? "text-faint" : w.change_pct >= 0 ? "num-up" : "num-down"}>
                        {fmt(w.price)} ({fmtPct(w.change_pct)})
                      </span>
                    </li>
                  ))
                )}
              </ul>
            )}
          </div>
          <div className="rounded-xl border border-line bg-panel" data-testid="sentiment">
            <button
              type="button"
              className="flex w-full items-center justify-between px-4 py-3 text-sm"
              data-testid="sent-toggle"
              aria-expanded={sentOpen}
              onClick={() => setSentOpen((v) => !v)}
            >
              News · {activeSymbol} <span aria-hidden>{sentOpen ? "▾" : "▸"}</span>
            </button>
            {sentOpen && (
              <ul className="max-h-56 space-y-3 overflow-auto border-t border-line px-3 py-3 text-sm" data-testid="sentiment-list">
                {sentiment.isLoading ? (
                  <li className="text-xs text-faint" data-testid="sentiment-empty">
                    Loading news for {activeSymbol}…
                  </li>
                ) : sentiment.isError ? (
                  <li className="text-xs text-faint" data-testid="sentiment-empty">
                    Sentiment request failed: {(sentiment.error as Error)?.message || "unknown error"}.{" "}
                    <button type="button" className="text-bronze underline" data-testid="sentiment-retry" onClick={() => sentiment.refetch()}>
                      Retry
                    </button>
                  </li>
                ) : ((sentiment.data?.items as SentimentRow[]) ?? []).length === 0 ? (
                  <li className="text-xs text-faint" data-testid="sentiment-empty">
                    {(sentiment.data as { caveat?: string | null } | undefined)?.caveat ||
                      (activeSymbol
                        ? `No recent news for ${activeSymbol} from Alpaca News.`
                        : "No recent news from Alpaca News.")}{" "}
                    {sentiment.data?.status === "unavailable" ? (
                      <button type="button" className="text-bronze underline" data-testid="sentiment-retry" onClick={() => sentiment.refetch()}>
                        Retry
                      </button>
                    ) : null}
                  </li>
                ) : (
                  ((sentiment.data?.items as SentimentRow[]) ?? []).map((s, i) => (
                    <li key={`${s.published_at}-${i}`}>
                      {s.url ? (
                        <a className="text-champagne underline" href={s.url} target="_blank" rel="noopener noreferrer">
                          {s.headline}
                        </a>
                      ) : (
                        <p className="text-champagne">{s.headline}</p>
                      )}
                      {s.blurb ? <p className="text-xs text-subtle">{s.blurb}</p> : null}
                      <p className="text-[10px] text-bronze">
                        {s.source} · {s.published_at}
                        {s.score_method ? ` · ${s.score_method}` : ""}
                      </p>
                    </li>
                  ))
                )}
              </ul>
            )}
          </div>
        </div>
      </section>

      {cert.selected ? (
        <PositionCertificateModal details={cert.selected} onDismiss={cert.dismiss} />
      ) : null}

      {showConnectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--apex-backdrop)]" data-testid="connect-modal">
          <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6">
            <h2 className="font-display text-2xl">Connect brokerage</h2>
            <p className="mt-2 text-sm text-subtle">Connect now, or continue and connect later. Later leaves a dismissible banner.</p>
            <div className="mt-6 flex gap-3">
              <button className="flex-1 rounded-md bg-gold py-2 text-ink" onClick={() => now.mutate()}>
                Connect brokerage now
              </button>
              <button className="flex-1 rounded-md border border-line py-2" data-testid="connect-later" onClick={() => later.mutate()}>
                Later
              </button>
            </div>
          </div>
        </div>
      )}

      <LegalFooter className="px-4 pb-6" />
    </div>
  );
}

function Stat({ label, value, testid }: { label: string; value: number; testid: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3" data-testid={testid}>
      <p className="text-xs uppercase tracking-wider text-bronze">{label}</p>
      <p className="font-mono text-2xl">{fmt(value)}</p>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-faint">{k}</dt>
      <dd className="font-mono">{v}</dd>
    </div>
  );
}

function fmt(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function fmtSigned(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n > 0) return `+${abs}`;
  if (n < 0) return `-${abs}`;
  return abs;
}
function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n).toFixed(2);
  if (n > 0) return `+${abs}%`;
  if (n < 0) return `-${abs}%`;
  return `${abs}%`;
}
function n(v?: number | null) {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  return v.toLocaleString();
}

function quoteSourceLabel(source?: string | null, secondary?: string | null, fundamentals?: string | null) {
  const parts = [
    source && source !== "unavailable" ? source : null,
    secondary,
    fundamentals && fundamentals !== "unavailable" && !secondary ? `Fundamentals · ${fundamentals}` : null,
  ]
    .filter(Boolean)
    .join(" · ")
    .replace(/\b(indicative|opra|alpaca|demo)\b/gi, "")
    .replace(/\s*·\s*·/g, " · ")
    .replace(/\s*·\s*\(/g, " (")
    .replace(/^[·\s]+|[·\s]+$/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return parts || "No live source";
}
