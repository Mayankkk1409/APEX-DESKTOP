import { formatCompositeScore } from "../lib/scoreFormat";
import { breakevenIvAssumptionNote, formatBreakevens, formatStrategyPremium } from "../lib/strategyFormat";
import { normalizeStrategyName } from "../lib/strategyDisplay";
import type { StrategyLayer } from "../types";

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatBound(value: number | null | undefined, unlimited: boolean | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return unlimited ? "Unlimited" : "—";
  }
  return fmtMoney(value);
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

  const score = data.composite_score ?? null;
  const strategyLabel = normalizeStrategyName(data.selected_strategy);
  const legCount = data.metrics?.legs?.length ?? 0;
  const blocked = legCount === 0 && data.tradeable === false;

  if (blocked) {
    return (
      <section
        className="sf-stage st-stage"
        data-testid="strategy-stage"
        data-strategy="blocked"
        data-tradeable="false"
      >
        <header className="sf-head">
          <div>
            <h1 className="sf-title">Strategy</h1>
            <p className="sf-sub">
              {symbol ?? ""}
              {expiry ? ` · expiry ${expiry}` : ""}
              {score != null ? ` · ${formatCompositeScore(score)}` : ""}
            </p>
          </div>
        </header>
        <article className="st-hero st-hero-blocked" data-testid="strategy-not-tradeable">
          <p className="st-kicker">Execution status</p>
          <h2 className="st-name">{strategyLabel}</h2>
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
  const primaryOptionLeg = metrics.legs?.find((leg) => leg.side === "call" || leg.side === "put");
  const anchorLeg = primaryOptionLeg
    ? {
        side: primaryOptionLeg.side,
        strike: primaryOptionLeg.strike,
        expiry: primaryOptionLeg.expiry,
      }
    : data.recommended_contract;
  const breakevenNote = breakevenIvAssumptionNote(metrics.breakevens, metrics);
  const equityBanner = data.equity_required
    ? data.equity_overlay_only
      ? "Assumes you already hold 100 shares per contract — options overlay only; stock is not submitted."
      : "Includes stock purchase/sale — review the stock leg alongside each option leg before submitting."
    : null;

  return (
    <section
      className="sf-stage st-stage"
      data-testid="strategy-stage"
      data-strategy={strategyLabel}
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
            {score != null ? ` · ${formatCompositeScore(score)}` : ""}
          </p>
        </div>
      </header>

      <article className="st-hero" data-testid="strategy-name">
        <p className="st-kicker">Best match</p>
        <h2 className="st-name">{strategyLabel}</h2>
        {data.auto_exec_line ? (
          <p className="st-leg-hint" data-testid="auto-exec-eligibility">
            {data.auto_exec_line}
          </p>
        ) : null}
        {data.risk_notes?.length ? (
          <ul className="st-leg-hint" data-testid="strategy-risk-notes">
            {data.risk_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
        {data.outlook ? (
          <p className="st-leg-hint" data-testid="strategy-outlook">
            Outlook: {data.outlook}
          </p>
        ) : null}
        {anchorLeg ? (
          <p className="st-leg-hint">
            Anchor leg: {anchorLeg.side} {anchorLeg.strike} · {anchorLeg.expiry}
          </p>
        ) : null}
        {equityBanner ? (
          <p className="st-equity-banner" data-testid="strategy-equity-banner">
            {equityBanner}
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
          <h2>Why it fits</h2>
          <p data-testid="strategy-why">{data.why_it_fits || data.why_recommended || "—"}</p>
          {data.selection_rationale ? (
            <p className="sf-panel-note" data-testid="strategy-selection-rationale">
              {data.selection_rationale}
            </p>
          ) : null}
        </article>

        <article className="sf-panel st-panel st-panel-wide">
          <h2>How to execute</h2>
          <p data-testid="strategy-how">{data.how_to_execute || "—"}</p>
        </article>
      </div>

      {legCount > 0 ? (
        <article className="sf-panel st-metrics" data-testid="strategy-metrics">
          <h2>Payoff profile</h2>
          <dl className="sf-kv">
            <div>
              <dt>Net debit / credit</dt>
              <dd data-testid="strategy-net">{formatStrategyPremium(metrics.net_debit_credit, metrics.net_type)}</dd>
            </div>
            <div>
              <dt>Max loss</dt>
              <dd data-testid="strategy-max-loss">
                {formatBound(metrics.max_loss, metrics.max_loss_unlimited_allowed)}
              </dd>
            </div>
            <div>
              <dt>Max profit</dt>
            <dd data-testid="strategy-max-profit">
                {formatBound(metrics.max_profit, metrics.max_profit_unlimited_allowed)}
              </dd>
            </div>
            <div>
              <dt>Breakeven(s)</dt>
              <dd data-testid="strategy-breakevens">{formatBreakevens(metrics.breakevens)}</dd>
            </div>
          </dl>
          {breakevenNote ? (
            <p className="sf-panel-note" data-testid="strategy-breakeven-iv-note">
              {breakevenNote}
            </p>
          ) : null}
          {metrics.legs?.length ? (
            <ul className="st-legs" data-testid="strategy-legs">
              {metrics.legs.map((leg, i) => (
                <li key={`${leg.symbol ?? leg.expiry ?? i}-${leg.strike}-${leg.action}`}>
                  <span className="st-leg-action">{leg.action}</span> {leg.side} {leg.strike}
                  {leg.expiry ? ` · exp ${leg.expiry}` : ""}
                  {leg.mid != null ? ` @ $${leg.mid.toFixed(2)}` : ""}
                  {leg.symbol ? ` · ${leg.symbol}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {metrics.notes ? <p className="sf-panel-note">{metrics.notes}</p> : null}
          {typeof data.strategies_evaluated === "number" ? (
            <p className="sf-panel-note" data-testid="strategies-evaluated">
              {data.strategies_evaluated} strategies evaluated
            </p>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}
