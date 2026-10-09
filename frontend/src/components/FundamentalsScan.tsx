import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { humanizeLabel } from "../lib/humanizeLabel";
import { formatEarningsDate } from "../lib/quoteMeta";
import type { FundamentalsLayer } from "../types";

function dash(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(2)}`;
}

/** Income-statement cells are USD thousands per NASDAQ table. */
function fmtIncomeThousands(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmtMoney(v * 1000);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

type FactorCard = { id: string; title: string; body: string };

function buildFactorCards(data: FundamentalsLayer): FactorCard[] {
  if (data.factor_cards?.length) return data.factor_cards;
  const h = data.company_health;
  const cal = data.earnings_calendar;
  const rot = data.sector_rotation;
  const rev = data.revenue;
  const eps = data.eps_trend;
  const analyst = data.analyst;
  return [
    {
      id: "sector",
      title: "Sector positioning",
      body:
        rot.reading ||
        (rot.sector && rot.etf
          ? `${data.symbol} is classified in ${rot.sector}, tracked via ${rot.etf} versus SPY.`
          : "Sector positioning unavailable."),
    },
    {
      id: "valuation",
      title: "Valuation",
      body:
        h.pe_ttm != null && h.spot != null
          ? `Trailing P/E ${fmtNum(h.pe_ttm, 1)} at spot ${fmtNum(h.spot, 2)}.`
          : h.pe_ttm != null
            ? `Trailing P/E ${fmtNum(h.pe_ttm, 1)}.`
            : "Valuation multiples unavailable.",
    },
    {
      id: "growth",
      title: "Growth",
      body: `Revenue YoY ${fmtPct(rev.yoy_pct)} (${humanizeLabel(rev.signal) || "—"}). EPS trend ${humanizeLabel(eps.trend) || "—"}.`,
    },
    {
      id: "analyst",
      title: "Analyst view",
      body: `${humanizeLabel(analyst.consensus_label) || "—"} · target ${fmtNum(analyst.price_target, 2)} vs spot ${fmtNum(h.spot, 2)} (${fmtPct(h.analyst_upside_pct)} implied).`,
    },
    {
      id: "earnings",
      title: "Earnings timing",
      body: (() => {
        const extra = cal as typeof cal & {
          date_status?: string;
          display?: string | null;
          earnings_applicable?: boolean;
          security_type?: string;
        };
        if (extra.earnings_applicable === false) {
          return `${data.symbol} is classified as ${extra.security_type || "ETF"}. An issuer earnings date does not apply.`;
        }
        const shown = formatEarningsDate(extra.display || cal.next_date, extra.date_status);
        if (shown) return `Next earnings ${shown}${cal.dte != null ? ` (${cal.dte} DTE)` : ""}.`;
        if (extra.date_status === "unknown") return "Earnings date is unknown. This is a data gap.";
        return cal.last_reported ? `Last reported ${cal.last_reported}.` : "Earnings timing unavailable.";
      })(),
    },
  ];
}

function FundFactorCards({ cards }: { cards: FactorCard[] }) {
  const [idx, setIdx] = useState(0);

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

  function go(delta: number) {
    setIdx((i) => Math.min(Math.max(cards.length - 1, 0), Math.max(0, i + delta)));
  }

  const active = cards[idx];

  if (!cards.length) {
    return <p className="sf-empty-inline">Factor analysis unavailable.</p>;
  }

  return (
    <div className="sf-factor-carousel-wrap">
      <div
        className="vol-carousel ta-carousel sf-factor-carousel"
        data-testid="fundamentals-factor-carousel"
        data-card-count={cards.length}
      >
        <button
          type="button"
          aria-label="Previous factor card"
          data-testid="fund-prev"
          className="ta-arrow"
          onClick={() => go(-1)}
        >
          ‹
        </button>
        <article className="ta-card" data-testid="fund-factor-card">
          <p className="ta-card-kicker">
            Fundamentals · {idx + 1} of {cards.length}
          </p>
          <h2 className="ta-card-title">{active?.title ?? "Factor"}</h2>
          <p className="ta-card-body">{active?.body ?? ""}</p>
        </article>
        <button
          type="button"
          aria-label="Next factor card"
          data-testid="fund-next"
          className="ta-arrow"
          onClick={() => go(1)}
        >
          ›
        </button>
      </div>
    </div>
  );
}

export function FundamentalsScan({
  symbol,
  initial,
}: {
  symbol: string;
  initial?: FundamentalsLayer | Record<string, unknown> | null;
}) {
  const q = useQuery({
    queryKey: ["fundamentals-deep", symbol],
    queryFn: () => api.fundamentalsDeep(symbol),
    enabled: Boolean(symbol),
    staleTime: 60_000,
    initialData: initial && "company_health" in (initial as object) ? (initial as FundamentalsLayer) : undefined,
  });

  const data = (q.data ?? initial) as FundamentalsLayer | undefined;
  if (!data || !data.company_health) {
    return (
      <section className="sf-stage" data-testid="fundamentals-stage" data-state="loading">
        <p className="sf-empty">
          {q.isError
            ? `Fundamentals request failed: ${(q.error as Error)?.message ?? "unknown error"}.`
            : `Loading fundamentals for ${symbol}…`}
        </p>
      </section>
    );
  }

  const h = data.company_health;
  const cal = data.earnings_calendar;
  const eps = data.eps_trend;
  const rev = data.revenue;
  const analyst = data.analyst;
  const factorCards = buildFactorCards(data);

  return (
    <section className="sf-stage" data-testid="fundamentals-stage">
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Fundamentals</h1>
          <p className="sf-sub">{data.name || symbol}</p>
        </div>
      </header>

      <div className="sf-metric-strip" data-testid="fundamentals-health">
        {(
          [
            ["EPS", fmtNum(h.eps_latest, 2)],
            ["Surprise", fmtPct(h.eps_surprise_pct)],
            ["Revenue YoY", fmtPct(h.revenue_yoy_pct)],
            ["Net income", fmtIncomeThousands(h.net_income)],
            ["P/E", fmtNum(h.pe_ttm, 1)],
            ["Target", fmtNum(h.analyst_target, 2)],
            ["Mkt cap", fmtMoney(h.market_cap)],
            ["52w high", fmtNum(h.week_52_high, 2)],
            ["52w low", fmtNum(h.week_52_low, 2)],
            ["Coverage", fmtNum(h.analyst_coverage, 0)],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="sf-metric">
            <p>{k}</p>
            <strong>{v}</strong>
          </div>
        ))}
      </div>

      <div className="sf-split sf-split-3">
        <article className="sf-panel">
          <h2>EPS trend</h2>
          <p className="sf-panel-note">
            {eps.trend === "consecutive_beats"
              ? `${eps.consecutive_beats} consecutive beats`
              : humanizeLabel(eps.trend)}
          </p>
          <ul className="sf-history">
            {(eps.history || []).slice(0, 4).map((row, i) => (
              <li key={i}>
                <span>{dash(row.fiscal_quarter)}</span>
                <span>{fmtNum(row.eps, 2)}</span>
                <span className={(row.surprise_pct ?? 0) >= 0 ? "num-up" : "num-down"}>{fmtPct(row.surprise_pct)}</span>
              </li>
            ))}
            {!eps.history?.length ? <li className="sf-empty-inline">—</li> : null}
          </ul>
        </article>

        <article className="sf-panel">
          <h2>Revenue YoY</h2>
          <p className={`sf-big ${rev.signal === "strong" ? "num-up" : rev.signal === "caution" ? "num-down" : ""}`}>
            {fmtPct(rev.yoy_pct)}
          </p>
          <p className="sf-panel-note">{rev.rule || ">15% strong · &lt;5% caution"}</p>
          <dl className="sf-kv">
            <div>
              <dt>{dash(rev.period_current)}</dt>
              <dd>{fmtIncomeThousands(rev.current)}</dd>
            </div>
            <div>
              <dt>{dash(rev.period_prior)}</dt>
              <dd>{fmtIncomeThousands(rev.prior)}</dd>
            </div>
            <div>
              <dt>Signal</dt>
              <dd>{humanizeLabel(rev.signal)}</dd>
            </div>
          </dl>
        </article>

        <article className="sf-panel" data-testid="fundamentals-calendar">
          <h2>Earnings calendar</h2>
          <dl className="sf-kv">
            <div>
              <dt>Next date</dt>
              <dd>{dash(cal.next_date)}</dd>
            </div>
            <div>
              <dt>DTE</dt>
              <dd>{cal.dte != null ? fmtNum(cal.dte, 0) : "—"}</dd>
            </div>
            <div>
              <dt>Last reported</dt>
              <dd>{dash(cal.last_reported)}</dd>
            </div>
          </dl>
        </article>
      </div>

      <div className="sf-split">
        <article className="sf-panel">
          <h2>Analyst consensus</h2>
          <p className="sf-big">{humanizeLabel(analyst.consensus_label)}</p>
          <dl className="sf-kv">
            <div>
              <dt>Target</dt>
              <dd>{fmtNum(analyst.price_target, 2)}</dd>
            </div>
            <div>
              <dt>Range</dt>
              <dd>
                {fmtNum(analyst.low_target, 0)} – {fmtNum(analyst.high_target, 0)}
              </dd>
            </div>
            <div>
              <dt>Buy / Hold / Sell</dt>
              <dd>
                {fmtNum(analyst.buy, 0)} / {fmtNum(analyst.hold, 0)} / {fmtNum(analyst.sell, 0)}
              </dd>
            </div>
            <div>
              <dt>Vs spot</dt>
              <dd>{fmtPct(h.analyst_upside_pct)}</dd>
            </div>
          </dl>
        </article>

        <article className="sf-panel" data-testid="fundamentals-factors">
          <h2>Factor analysis</h2>
          <FundFactorCards cards={factorCards} />
        </article>
      </div>
    </section>
  );
}
