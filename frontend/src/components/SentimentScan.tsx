import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { humanizeLabel } from "../lib/humanizeLabel";
import type { SentimentArticle, SentimentLayer } from "../types";

function dash(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

function gaugeOffset(score: number | null): number {
  if (score === null || Number.isNaN(score)) return 126;
  const t = (Math.max(-100, Math.min(100, score)) + 100) / 200;
  return 126 * (1 - t);
}

function sentimentBand(data: SentimentLayer): string {
  if (data.band) return data.band;
  const score = data.score;
  if (score === null || score === undefined) return "Neutral";
  if (score <= -60) return "Very Bearish";
  if (score <= -20) return "Bearish";
  if (score >= 60) return "Very Bullish";
  if (score >= 20) return "Bullish";
  return "Neutral";
}

function fmtPublished(at: string | null | undefined): string {
  if (!at) return "—";
  return at.slice(0, 16).replace("T", " ");
}

function openArticle(article: SentimentArticle) {
  const url = article.url?.trim();
  if (url) {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

export function SentimentScan({
  symbol,
  expiry,
  initial,
}: {
  symbol: string;
  expiry: string;
  initial?: SentimentLayer | Record<string, unknown> | null;
}) {
  const q = useQuery({
    queryKey: ["sentiment-deep", symbol, expiry || ""],
    queryFn: () => api.sentimentDeep(symbol, expiry || undefined),
    enabled: Boolean(symbol),
    staleTime: 30_000,
    initialData: initial && "components" in (initial as object) ? (initial as SentimentLayer) : undefined,
  });

  const data = (q.data ?? initial) as SentimentLayer | undefined;
  if (!data || !data.components) {
    return (
      <section className="sf-stage" data-testid="sentiment-stage" data-state="loading">
        <p className="sf-empty">
          {q.isError
            ? `Sentiment request failed: ${(q.error as Error)?.message ?? "unknown error"}.`
            : `Loading sentiment for ${symbol}…`}
        </p>
      </section>
    );
  }

  const band = sentimentBand(data);
  const bias = data.bias || band.toLowerCase().replace(/\s+/g, "-");
  const displayScore =
    data.score_0_100 != null && !Number.isNaN(data.score_0_100) ? Math.round(data.score_0_100) : null;
  const news = data.components.news;
  const flow = data.components.options_flow;
  const pc = data.components.put_call;
  const alert = data.earnings_alert;
  const flowContext = [flow.volume_context, flow.notional_skew].filter(Boolean).join(" · ");

  return (
    <section className="sf-stage" data-testid="sentiment-stage" data-bias={bias}>
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Sentiment</h1>
          <p className="sf-sub">{symbol}</p>
        </div>
      </header>

      <div className="sf-gauge-row">
        <div
          className="sf-gauge"
          data-testid="sentiment-gauge"
          aria-label={
            displayScore != null ? `Sentiment ${band}, score ${displayScore}` : `Sentiment ${band}`
          }
        >
          <svg viewBox="0 0 120 70" className="sf-gauge-svg">
            <path d="M10 60 A50 50 0 0 1 110 60" className="sf-gauge-track" />
            <path
              d="M10 60 A50 50 0 0 1 110 60"
              className={`sf-gauge-fill is-${bias}`}
              strokeDasharray="126"
              strokeDashoffset={gaugeOffset(data.score)}
            />
          </svg>
          <p className={`sf-gauge-value is-${bias}`}>
            {displayScore != null ? (
              <>
                <span className="sf-gauge-band">{band}</span>
                <span className="sf-gauge-sep"> · </span>
                <span className="sf-gauge-score">{displayScore}</span>
              </>
            ) : (
              band
            )}
          </p>
        </div>
        <div className="sf-gauge-rationale">
          <p className="sf-narrative" data-testid="sentiment-synthesis">
            {data.narrative}
          </p>
        </div>
      </div>

      {alert?.message ? (
        <div
          className={`sf-alert ${alert.active ? "is-hot" : ""}`}
          data-testid="sentiment-earnings-alert"
          data-active={alert.active ? "true" : "false"}
        >
          <span className="sf-alert-kicker">{alert.active ? "Earnings alert" : "Earnings context"}</span>
          <p>{alert.message}</p>
        </div>
      ) : null}

      <article className="sf-panel">
        <h2>Options flow summary</h2>
        {flowContext ? <p className="sf-panel-note">{flowContext}</p> : null}
        <dl className="sf-kv">
          <div>
            <dt>Call volume</dt>
            <dd>{fmtNum(flow.call_volume, 0)}</dd>
          </div>
          <div>
            <dt>Put volume</dt>
            <dd>{fmtNum(flow.put_volume, 0)}</dd>
          </div>
          <div>
            <dt>P/C volume</dt>
            <dd>{fmtNum(flow.put_call_volume_ratio ?? pc.ratio, 3)}</dd>
          </div>
          <div>
            <dt>P/C signal</dt>
            <dd>{humanizeLabel(flow.put_call_signal ?? pc.signal)}</dd>
          </div>
          <div>
            <dt>Call notional proxy</dt>
            <dd>{fmtUsd(flow.call_notional_proxy)}</dd>
          </div>
          <div>
            <dt>Put notional proxy</dt>
            <dd>{fmtUsd(flow.put_notional_proxy)}</dd>
          </div>
          <div>
            <dt>Net notional</dt>
            <dd>{fmtUsd(flow.net_notional_proxy)}</dd>
          </div>
          <div>
            <dt>Unusual prints</dt>
            <dd>{fmtNum(flow.unusual_activity_count, 0)}</dd>
          </div>
        </dl>
      </article>

      <article className="sf-panel sf-news" data-testid="sentiment-news">
        <h2>
          News <span>{news.count}</span>
        </h2>
        {!news.articles?.length ? (
          <p className="sf-empty-inline">{news.error || "No news articles for this symbol."}</p>
        ) : (
          <ul className="sf-news-list">
            {news.articles.map((a, i) => (
              <li key={`${a.published_at}-${i}`}>
                <div className="sf-news-main">
                  <button type="button" className="sf-news-link" onClick={() => openArticle(a)}>
                    {a.headline || "Untitled"}
                  </button>
                </div>
                <div className="sf-news-meta">
                  <span>{fmtPublished(a.published_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  );
}
