import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { humanizeLabel } from "../lib/humanizeLabel";
import { clearNewsRetry, isNewsRateLimitMessage, newsRetryDelay, noteNewsRateLimit, scrubRateLimitCopy, visibleNewsError } from "../lib/newsFeed";
import type { SentimentLayer } from "../types";

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

export function SentimentScan({
  symbol,
  expiry,
  initial,
}: {
  symbol: string;
  expiry: string;
  initial?: SentimentLayer | Record<string, unknown> | null;
}) {
  const qc = useQueryClient();
  const newsKey = `deep:${symbol}:${expiry || ""}`;
  const q = useQuery({
    queryKey: ["sentiment-deep", symbol, expiry || ""],
    queryFn: async () => {
      const next = (await api.sentimentDeep(symbol, expiry || undefined)) as SentimentLayer;
      const newsError = next.components?.news?.error;
      if (!isNewsRateLimitMessage(newsError)) {
        clearNewsRetry(newsKey);
        return next;
      }
      noteNewsRateLimit(newsKey);
      const previous = qc.getQueryData<SentimentLayer>(["sentiment-deep", symbol, expiry || ""]);
      const previousArticles = previous?.components?.news?.articles;
      if (previousArticles?.length && previous) {
        return {
          ...next,
          narrative: scrubRateLimitCopy(previous.narrative || next.narrative),
          components: {
            ...next.components,
            news: { ...previous.components.news, error: null },
          },
        };
      }
      return {
        ...next,
        narrative: scrubRateLimitCopy(next.narrative),
        components: {
          ...next.components,
          news: { ...next.components.news, error: null, status: "empty" },
        },
      };
    },
    enabled: Boolean(symbol),
    staleTime: 60_000,
    retry: (failureCount, error) => !isNewsRateLimitMessage((error as Error)?.message) && failureCount < 1,
    refetchInterval: () => newsRetryDelay(newsKey),
    initialData: initial && "components" in (initial as object) ? (initial as SentimentLayer) : undefined,
  });

  const data = (q.data ?? initial) as SentimentLayer | undefined;
  const rawNewsError = data?.components?.news?.error;
  useEffect(() => {
    const message = (q.error as Error | undefined)?.message;
    if (isNewsRateLimitMessage(rawNewsError) || isNewsRateLimitMessage(message)) noteNewsRateLimit(newsKey);
  }, [rawNewsError, newsKey, q.error]);
  if (!data || !data.components) {
    const failure = q.isError ? visibleNewsError((q.error as Error)?.message) : null;
    const rateLimited = q.isError && isNewsRateLimitMessage((q.error as Error)?.message);
    return (
      <section className="sf-stage" data-testid="sentiment-stage" data-state="loading">
        <p className="sf-empty">
          {failure
            ? `Sentiment request failed: ${failure}.`
            : rateLimited
              ? `No recent news for ${symbol} from Alpaca News.`
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
  const newsError = visibleNewsError(news.error);
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
            {scrubRateLimitCopy(data.narrative)}
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
          {alert.source ? <p className="sf-panel-note">{alert.source}</p> : null}
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
        <p className="sf-panel-note">
          {(news.source || "Alpaca News")} · {news.method || "lexicon_v1"}
        </p>
        {!news.articles?.length ? (
          <p className="sf-empty-inline" data-testid="sentiment-news-empty">
            {newsError ? (
              <>
                {newsError.endsWith(".") ? newsError : `${newsError}.`}{" "}
                <button type="button" className="sf-news-link" data-testid="sentiment-news-retry" onClick={() => q.refetch()}>
                  Retry
                </button>
              </>
            ) : (
              `No recent news for ${symbol} from Alpaca News.`
            )}
          </p>
        ) : (
          <ul className="sf-news-list">
            {news.articles.map((a, i) => (
              <li key={`${a.published_at}-${i}`}>
                <div className="sf-news-main">
                  {a.url ? (
                    <a className="sf-news-link" href={a.url} target="_blank" rel="noopener noreferrer">
                      {a.headline || "Headline unavailable"}
                    </a>
                  ) : (
                    <span className="sf-news-link">{a.headline || "Headline unavailable"}</span>
                  )}
                </div>
                <div className="sf-news-meta">
                  <span>{a.source || news.source || "—"}</span>
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
