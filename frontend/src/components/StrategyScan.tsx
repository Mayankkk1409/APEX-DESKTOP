import { formatBreakevens, formatStrategyPremium } from "../lib/strategyFormat";
import type { StrategyLayer } from "../types";

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export function StrategyScan({
  symbol,
  expiry,
  initial,
}: {
  symbol?: string;
  expiry?: string;
  initial?: StrategyLayer | null;
}) {
  const data = initial;

  if (!data?.selected_strategy) {
    return (
      <section className="sf-stage st-stage" data-testid="strategy-stage" data-state="loading">
        <p className="sf-empty">Loading strategy recommendation…</p>
      </section>
    );
  }

  const blocked = data.tradeable === false || data.execution_tier === "blocked";
  const noTrade = blocked || data.selected_strategy.includes("NO TRADE");

  if (blocked) {
    return (
      <section
        className="sf-stage st-stage"
        data-testid="strategy-stage"
        data-strategy="blocked"
        data-no-trade="true"
        data-tradeable="false"
      >
        <header className="sf-head">
          <div>
            <h1 className="sf-title">Strategy</h1>
            <p className="sf-sub">
              {symbol ?? ""}
              {expiry ? ` · expiry ${expiry}` : ""}
            </p>
          </div>
        </header>
        <article className="st-hero st-hero-blocked" data-testid="strategy-not-tradeable">
          <p className="st-kicker">Execution status</p>
          <h2 className="st-name is-no-trade">{data.selected_strategy}</h2>
          <p className="st-blocked-copy" data-testid="strategy-blocked-copy">
            {data.why_recommended || data.narrative}
          </p>
        </article>
      </section>
    );
  }

  const metrics = data.metrics ?? {
    max_loss: null,
    max_profit: null,
    net_debit_credit: null,
    net_type: null,
    breakevens: [],
    legs: [],
  };

  return (
    <section
      className="sf-stage st-stage"
      data-testid="strategy-stage"
      data-strategy={data.selected_strategy}
      data-no-trade={noTrade ? "true" : "false"}
      data-tradeable="true"
      data-execution-tier={data.execution_tier ?? ""}
    >
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Strategy</h1>
          <p className="sf-sub">
            {symbol ?? ""}
            {expiry ? ` · expiry ${expiry}` : ""}
            {data.direction ? ` · ${data.direction}` : ""}
            {data.vol_signal ? ` · vol ${data.vol_signal.replaceAll("_", " ")}` : ""}
          </p>
        </div>
      </header>

      <article className="st-hero" data-testid="strategy-name">
        <p className="st-kicker">Recommended structure</p>
        <h2 className={`st-name ${noTrade ? "is-no-trade" : ""}`}>{data.selected_strategy}</h2>
        {!noTrade && data.recommended_contract ? (
          <p className="st-leg-hint">
            Anchor leg: {data.recommended_contract.side} {data.recommended_contract.strike} · {data.recommended_contract.expiry}
          </p>
        ) : null}
      </article>

      <div className="st-grid">
        {data.what_is_this ? (
          <article className="sf-panel st-panel">
            <h2>What is this strategy?</h2>
            <p data-testid="strategy-what">{data.what_is_this}</p>
          </article>
        ) : null}

        <article className="sf-panel st-panel">
          <h2>Why recommended</h2>
          <p data-testid="strategy-why">{data.why_recommended || "—"}</p>
        </article>

        <article className="sf-panel st-panel st-panel-wide">
          <h2>How to execute</h2>
          <p data-testid="strategy-how">{data.how_to_execute || "—"}</p>
        </article>
      </div>

      {!noTrade ? (
        <article className="sf-panel st-metrics" data-testid="strategy-metrics">
          <h2>Payoff profile</h2>
          <dl className="sf-kv">
            <div>
              <dt>Net debit / credit</dt>
              <dd data-testid="strategy-net">{formatStrategyPremium(metrics.net_debit_credit, metrics.net_type)}</dd>
            </div>
            <div>
              <dt>Max loss</dt>
              <dd data-testid="strategy-max-loss">{fmtMoney(metrics.max_loss)}</dd>
            </div>
            <div>
              <dt>Max profit</dt>
              <dd data-testid="strategy-max-profit">
                {metrics.max_profit === null ? "Unlimited" : fmtMoney(metrics.max_profit)}
              </dd>
            </div>
            <div>
              <dt>Breakeven(s)</dt>
              <dd data-testid="strategy-breakevens">{formatBreakevens(metrics.breakevens)}</dd>
            </div>
          </dl>
          {metrics.legs?.length ? (
            <ul className="st-legs">
              {metrics.legs.map((leg, i) => (
                <li key={`${leg.symbol ?? i}-${leg.strike}`}>
                  <span className="st-leg-action">{leg.action}</span> {leg.side} {leg.strike}
                  {leg.mid != null ? ` @ $${leg.mid.toFixed(2)}` : ""}
                  {leg.symbol ? ` · ${leg.symbol}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {metrics.notes ? <p className="sf-panel-note">{metrics.notes}</p> : null}
        </article>
      ) : null}
    </section>
  );
}
