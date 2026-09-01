import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import {
  buildLadder,
  fmtInt,
  fmtNum,
  fmtSigned,
  gateSummary,
  greekProvenanceIsMixed,
  type ChainLadderRow,
} from "../lib/optionsChain";
import { scoreTier } from "../lib/chartHighlight";
import { useSession } from "../store";
import type { ChainAnalysis, ChainContractRow, RecommendedContract } from "../types";

type Column = { id: string; label: string; title: string };

/** Professional chain columns — quotes + Greeks only. Gate narrative lives in the carousel. */
const COLUMNS: Column[] = [
  { id: "bid", label: "Bid", title: "Best bid" },
  { id: "ask", label: "Ask", title: "Best offer" },
  { id: "last", label: "Last", title: "Last traded price" },
  { id: "change", label: "Chg", title: "Change versus prior close" },
  { id: "volume", label: "Vol", title: "Contracts traded today" },
  { id: "oi", label: "OI", title: "Open interest" },
  { id: "iv", label: "IV", title: "Implied volatility" },
  { id: "delta", label: "Δ", title: "Delta" },
  { id: "gamma", label: "Γ", title: "Gamma" },
  { id: "theta", label: "Θ", title: "Theta" },
  { id: "vega", label: "ν", title: "Vega" },
  { id: "rho", label: "ρ", title: "Rho" },
];

export function OptionsChainGreeks({
  symbol,
  expiry,
  initial,
  executionScore,
}: {
  symbol: string;
  expiry: string;
  initial?: ChainAnalysis;
  /** Scan composite score — drives highlight / recommended-contract tiers. */
  executionScore?: number | null;
}) {
  const [idx, setIdx] = useState(0);
  const sessionRecommended = useSession((s) => s.recommendedContract);

  const chain = useQuery({
    queryKey: ["chain-analysis", symbol, expiry],
    queryFn: () => api.optionsAnalysis(symbol, expiry),
    enabled: Boolean(symbol && expiry),
    staleTime: 15_000,
  });

  const analysis: ChainAnalysis | null = chain.data ?? initial ?? null;
  const tier = scoreTier(analysis?.execution_score ?? executionScore ?? null);
  const blocked = tier === "blocked";
  const recommended: RecommendedContract | null = blocked
    ? null
    : analysis?.recommendedContract ?? sessionRecommended ?? null;
  const showRecommended = !blocked && recommended != null;
  const cards = analysis?.cards ?? [];
  const contracts = analysis?.contracts ?? [];
  const ladder = useMemo(
    () => buildLadder(contracts, analysis?.spot ?? null, showRecommended ? recommended : null),
    [contracts, analysis?.spot, recommended, showRecommended],
  );
  const mixedGreeks = useMemo(() => greekProvenanceIsMixed(contracts), [contracts]);
  const callColumns = COLUMNS;

  const tableWrap = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const wrap = tableWrap.current;
    if (!wrap) return;
    const focusRow =
      wrap.querySelector<HTMLElement>('.chain-row[data-recommended="true"]') ??
      wrap.querySelector<HTMLElement>(".chain-row");
    const strikeCell = focusRow?.querySelector<HTMLElement>(".chain-strike");
    if (strikeCell) wrap.scrollLeft = Math.max(0, strikeCell.offsetLeft + strikeCell.offsetWidth / 2 - wrap.clientWidth / 2);
    if (focusRow) wrap.scrollTop = Math.max(0, focusRow.offsetTop - wrap.clientHeight / 2);
  }, [ladder, recommended]);

  useEffect(() => {
    setIdx((i) => (cards.length ? Math.min(i, cards.length - 1) : 0));
  }, [cards.length]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setIdx((i) => Math.min(i + 1, Math.max(cards.length - 1, 0)));
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setIdx((i) => Math.max(i - 1, 0));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cards.length]);

  const swipeX = useRef(0);
  function go(delta: number) {
    setIdx((i) => Math.min(Math.max(cards.length - 1, 0), Math.max(0, i + delta)));
  }

  if (!expiry && !analysis) {
    return (
      <section className="chain-stage" data-testid="chain-stage" data-chain-state="no-expiry">
        <p className="chain-empty" data-testid="chain-empty">
          No expiry is selected for this scan session. Pick an expiration on the dashboard expiry picker and re-run the
          scan.
        </p>
      </section>
    );
  }

  if (!analysis) {
    return (
      <section className="chain-stage" data-testid="chain-stage" data-chain-state="loading">
        <p className="chain-empty" data-testid="chain-empty">
          {chain.isError
            ? `Chain request failed: ${(chain.error as Error)?.message ?? "unknown error"}.`
            : `Loading the ${symbol} ${expiry} option chain…`}
        </p>
      </section>
    );
  }

  const src = analysis.data_source;
  const active = cards[idx];
  const caveats = src.caveats ?? [];
  const quietFootnote =
    mixedGreeks && src.model_greeks > 0
      ? `${src.model_greeks} of ${analysis.summary.contract_count} Greeks filled locally where the vendor omitted them.`
      : null;
  const emptyMessage =
    src.status === "no_keys"
      ? "Configure market data keys in .env, then restart the backend. No simulated chain is shown."
      : src.status === "unsupported_underlying"
        ? analysis.cards[0]?.body ||
          `${analysis.symbol} is a cash-settled index with no listed options chain on this vendor. Scan the tracking ETF (for example SPY for SPX) for a live chain.`
        : (analysis.cards[0]?.body ?? "No contracts to display.");

  return (
    <section
      className="chain-stage"
      data-testid="chain-stage"
      data-chain-state={src.status}
      data-expiry={analysis.expiry ?? expiry ?? ""}
      data-execution-tier={tier}
      data-vega-blocked={analysis.vega_cap.blocks_long_premium ? "true" : "false"}
    >
      <header className="chain-head" data-testid="chain-head">
        <div className="chain-head-main">
          <h1 className="chain-title">
            {analysis.symbol}
            {analysis.expiry ? ` · ${analysis.expiry}` : ""}
          </h1>
        </div>
        {!src.is_live && (
          <p className="chain-source-quiet is-degraded" data-testid="chain-source-badge" role="status">
            {src.label}
          </p>
        )}
      </header>

      {!src.is_live && (
        <p className="chain-warn" data-testid="chain-degraded-warning" role="alert">
          {src.label}. Chain quotes on this screen are not live vendor data.
        </p>
      )}

      {!src.is_live && caveats.length > 0 && ladder.length === 0 && (
        <p className="chain-warn chain-caveats" data-testid="chain-caveats" role="note">
          {caveats.join(" ")}
        </p>
      )}

      {blocked && (
        <p className="chain-warn chain-infeasible" data-testid="chain-infeasible" role="alert">
          APEX analysis has detected a not feasible or not tradeable scenario.
        </p>
      )}

      {ladder.length === 0 ? (
        <p className="chain-empty" data-testid="chain-empty">
          {emptyMessage}
        </p>
      ) : (
        <div className="chain-table-wrap" data-testid="chain-table-wrap" ref={tableWrap}>
          <table className="chain-table" data-testid="chain-table" data-rows={ladder.length}>
            <thead>
              <tr className="chain-group-row">
                <th colSpan={callColumns.length}>Calls</th>
                <th className="chain-strike-head">Strike</th>
                <th colSpan={COLUMNS.length}>Puts</th>
              </tr>
              <tr>
                {callColumns.map((c) => (
                  <th key={`c-${c.id}`} title={c.title}>
                    {c.label}
                  </th>
                ))}
                <th className="chain-strike-head" title="Strike price">
                  Strike
                </th>
                {COLUMNS.map((c) => (
                  <th key={`p-${c.id}`} title={c.title}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ladder.map((row) => (
                <LadderRow key={row.strike} row={row} columns={COLUMNS} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {quietFootnote && (
        <p className="chain-footnote" data-testid="chain-footnote">
          {quietFootnote}
        </p>
      )}

      <div
        className="ta-carousel chain-carousel"
        data-testid="chain-carousel"
        data-card-count={cards.length}
        onWheel={(e) => {
          if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 24) {
            e.preventDefault();
            go(e.deltaX > 0 ? 1 : -1);
          }
        }}
        onTouchStart={(e) => {
          swipeX.current = e.touches[0].clientX;
        }}
        onTouchEnd={(e) => {
          const dx = e.changedTouches[0].clientX - swipeX.current;
          if (dx < -40) go(1);
          if (dx > 40) go(-1);
        }}
      >
        <button type="button" aria-label="Previous chain analysis" data-testid="chain-prev" className="ta-arrow" onClick={() => go(-1)}>
          ‹
        </button>
        <article className="ta-card" data-testid="chain-card" data-bias={active?.bias ?? "neutral"} data-card-id={active?.id ?? ""}>
          <p className="ta-card-kicker">
            Chain &amp; Greeks · {cards.length ? idx + 1 : 0} of {cards.length}
            {active?.verdict ? ` · ${active.verdict}` : ""}
          </p>
          <h2 className="ta-card-title">{active?.title ?? "Analysis"}</h2>
          <p className="ta-card-body">{active?.body ?? "No analysis computed for this chain."}</p>
        </article>
        <button type="button" aria-label="Next chain analysis" data-testid="chain-next" className="ta-arrow" onClick={() => go(1)}>
          ›
        </button>
      </div>
    </section>
  );
}

function LadderRow({ row, columns }: { row: ChainLadderRow; columns: Column[] }) {
  return (
    <tr
      className="chain-row"
      data-testid={`chain-row-${row.strike}`}
      data-recommended={row.isRecommended ? "true" : "false"}
      data-reject={row.hasReject ? "true" : "false"}
      data-uoa={row.hasUoa ? "true" : "false"}
    >
      {columns.map((c) => (
        <Cell
          key={`c-${c.id}`}
          column={c}
          contract={row.call}
          itm={row.itmSide === "call"}
          recommended={row.recommendedSide === "call"}
        />
      ))}
      <th className="chain-strike" scope="row">
        {row.strike.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        {row.hasUoa && (
          <span className="chain-soft-flag is-uoa" title="Unusual options activity on this strike">
            ◆
          </span>
        )}
        {row.hasReject && (
          <span className="chain-soft-flag is-wide" title={gateSummary(row.call?.verdict ?? row.put?.verdict)}>
            ▸
          </span>
        )}
      </th>
      {columns.map((c) => (
        <Cell
          key={`p-${c.id}`}
          column={c}
          contract={row.put}
          itm={row.itmSide === "put"}
          recommended={row.recommendedSide === "put"}
        />
      ))}
    </tr>
  );
}

function Cell({
  column,
  contract,
  itm,
  recommended,
}: {
  column: Column;
  contract: ChainContractRow | null;
  itm: boolean;
  recommended: boolean;
}) {
  const cls = [itm ? "chain-cell is-itm" : "chain-cell", recommended ? "is-recommended-leg" : ""].filter(Boolean).join(" ");
  if (!contract) {
    return (
      <td className={cls} title="No contract listed on this side of the strike.">
        —
      </td>
    );
  }
  const v = contract.verdict;
  const content: Record<string, { text: string; flag?: "good" | "bad"; title?: string }> = {
    bid: { text: fmtNum(contract.bid), title: contract.bid_size !== null ? `size ${fmtInt(contract.bid_size)}` : undefined },
    ask: { text: fmtNum(contract.ask), title: contract.ask_size !== null ? `size ${fmtInt(contract.ask_size)}` : undefined },
    last: { text: fmtNum(contract.last) },
    change: { text: fmtSigned(contract.change), flag: contract.change === null ? undefined : contract.change >= 0 ? "good" : "bad" },
    volume: { text: fmtInt(contract.volume) },
    oi: { text: fmtInt(contract.open_interest) },
    iv: { text: contract.iv == null ? "—" : `${(contract.iv * 100).toFixed(1)}%` },
    delta: { text: fmtNum(contract.delta, 4) },
    gamma: { text: fmtNum(contract.gamma, 4) },
    theta: { text: fmtNum(contract.theta, 4) },
    vega: { text: fmtNum(contract.vega, 4) },
    rho: { text: fmtNum(contract.rho, 4) },
  };
  const cell = content[column.id] ?? { text: "—" };
  const tip = [cell.title, v ? gateSummary(v) : null].filter(Boolean).join(" · ") || column.title;
  return (
    <td className={cls} data-flag={cell.flag ?? ""} title={tip}>
      {cell.text}
    </td>
  );
}
