import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../../api";
import { useSession } from "../../store";
import type { VolatilitySnapshot } from "../../types";
import { CatalystCalendar } from "./CatalystCalendar";
import { IvHvChart } from "./IvHvChart";
import { VolAnalysisCards } from "./VolAnalysisCards";

function fmtPct(v: number | null | undefined, digits = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function ivHistoryHint(data: VolatilitySnapshot | null): string | undefined {
  const pts = Math.floor(data?.iv_history_points ?? 0);
  if (data?.iv_rank != null || data?.iv_percentile != null) return undefined;
  const bars = data?.series?.bar_count ?? 0;
  if (pts > 0) return `Need ≥20 IV pts (${pts} so far)`;
  if (bars >= 20) return undefined;
  return undefined;
}

export function VolatilityScan({
  symbol,
  expiry,
  initial,
}: {
  symbol: string;
  expiry: string;
  initial?: VolatilitySnapshot | null;
}) {
  const recommendedContract = useSession((s) => s.recommendedContract);

  const vol = useQuery({
    queryKey: ["volatility", symbol, expiry, recommendedContract?.contract_id, recommendedContract?.strike, recommendedContract?.side],
    queryFn: () => api.volatility(symbol, expiry || undefined, recommendedContract),
    enabled: Boolean(symbol),
    staleTime: 20_000,
  });

  const events = useQuery({
    queryKey: ["volatility-events", symbol],
    queryFn: () => api.volatilityEvents(symbol),
    enabled: Boolean(symbol),
    staleTime: 60_000,
  });

  const data: VolatilitySnapshot | null = vol.data ?? initial ?? null;
  const series = data?.series;
  const cards = data?.cards ?? [];
  const rec = data?.recommended_contract ?? recommendedContract;

  const ivHint = ivHistoryHint(data);

  const metrics = useMemo(
    () => [
      {
        k: rec ? `${rec.strike} ${rec.side.toUpperCase()} IV` : "Contract IV",
        v: fmtPct(data?.contract_iv ?? data?.iv ?? null),
      },
      { k: "ATM IV", v: fmtPct(data?.atm_iv ?? null) },
      { k: "30D HV", v: fmtPct(data?.hv ?? null) },
      { k: "DTE", v: data?.dte != null ? String(data.dte) : "—" },
      { k: "IV Rank", v: fmtNum(data?.iv_rank ?? null), hint: ivHint },
      { k: "HV Rank", v: fmtNum(data?.hv_rank ?? null) },
      { k: "IV %ile", v: fmtNum(data?.iv_percentile ?? null), hint: ivHint },
      { k: "HV %ile", v: fmtNum(data?.hv_percentile ?? null) },
      {
        k: "1σ move",
        v:
          data?.expected_move?.dollars != null
            ? `±${fmtNum(data.expected_move.dollars, 2)} (${fmtNum(data.expected_move.percent, 2)}%)`
            : "—",
      },
    ],
    [data, rec, ivHint],
  );

  if (!expiry) {
    return (
      <section className="vol-stage" data-testid="volatility-layer" data-vol-state="no-expiry">
        <p className="vol-empty">
          No expiry is selected for this scan session. Pick an expiration on the dashboard and re-run Deep Scan so DTE,
          ATM IV, and expected move can be computed against that date.
        </p>
      </section>
    );
  }

  return (
    <section className="vol-stage" data-testid="volatility-layer">
      <header className="vol-header vol-header-centered">
        <h1 className="vol-title font-display text-xl text-champagne">
          {symbol} · expiry {expiry}
        </h1>
      </header>

      <div className="vol-metrics" data-testid="vol-metrics">
        {metrics.map((m) => (
          <div key={m.k} className="vol-metric">
            <p className="vol-metric-k">{m.k}</p>
            <p className="vol-metric-v">{m.v}</p>
            {"hint" in m && m.hint ? <p className="vol-metric-hint">{m.hint}</p> : null}
          </div>
        ))}
      </div>

      <IvHvChart
        hvSeries={series?.hv_series ?? {}}
        windowsAvailable={series?.windows_available ?? []}
        currentIv={data?.contract_iv ?? data?.iv ?? null}
        ivSeries={series?.iv_series}
        contractLabel={
          rec ? `${rec.strike} ${rec.side.toUpperCase()} IV` : data?.iv != null ? "Contract IV" : undefined
        }
      />

      <CatalystCalendar
        tickerEvents={events.data?.ticker_events ?? []}
        marketEvents={events.data?.market_events ?? []}
        notes={events.data?.notes}
        symbol={symbol}
        loading={events.isLoading}
      />

      <VolAnalysisCards cards={cards} />

      {data?.notes?.length ? (
        <ul className="vol-notes" data-testid="vol-notes">
          {data.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
