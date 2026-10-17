import { useState } from "react";
import { scoreTier } from "../lib/chartHighlight";
import { fitText, orientShareLevels } from "../lib/equityLevels";
import { presentSource } from "../lib/sourceLabel";

type Analyst = {
  analyst?: string | null;
  firm?: string | null;
  rating?: string | null;
  price_target?: number | null;
  currency?: string | null;
  date?: string | null;
  source?: string | null;
  url?: string | null;
};

type Plan = {
  action?: string;
  why?: string;
  horizon?: { label?: string; detail?: string; day_basis?: string };
  levels?: {
    entry?: number | null;
    entry_label?: string;
    stop?: number | null;
    stop_basis?: string;
    take_profit?: number | null;
    exit_target?: number | null;
    exit_note?: string;
    reward_risk?: number | null;
  };
  scores?: {
    technical?: number | null;
    sentiment?: number | null;
    fundamental?: number | null;
    risk?: number | null;
    overall?: number | null;
    reweighted?: string[];
    contributions?: { layer: string; weight: number; score: number; points: number }[];
  };
  weight_policy?: string;
  scorecard?: {
    bull?: { earned?: number; possible?: number; passes?: boolean; points?: Record<string, number | null> };
    bear?: { earned?: number; possible?: number; passes?: boolean; points?: Record<string, number | null> };
    act_at?: number;
    max?: number;
  };
  technical_evidence?: string[];
  confirmed_patterns?: { name?: string; direction?: string; status?: string; strength?: number; timeframe?: string }[];
  developing_patterns?: { name?: string; direction?: string; status?: string }[];
  news?: { headline?: string; published?: string; source?: string; url?: string }[];
  fundamentals_notes?: string[];
  instrument?: string;
  earnings?: { date?: string | null; confirmed?: boolean; inside_holding_window?: boolean; source?: string | null };
  volume?: { last?: number; average?: number; ratio?: number; regime?: string };
  short_note?: string;
  analysts?: Analyst[];
  analyst_basis?: string;
  analyst_note?: string;
  consensus?: {
    label?: string | null;
    price_target?: number | null;
    source?: string | null;
    status?: string | null;
    buy?: number | null;
    hold?: number | null;
    sell?: number | null;
  } | null;
  as_of?: string | null;
  quote_session?: string;
  risk_profile?: string;
  trend?: string;
  direction?: string;
  fit?: string;
  holds_shares?: boolean;
  market?: {
    price?: number | null;
    atr?: number | null;
    atr_pct?: number | null;
    spread_pct?: number | null;
    support?: number | null;
    resistance?: number | null;
  };
};

function money(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function score(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  return value.toFixed(1);
}

function resolvePlanLevels(plan: Plan): Plan {
  const levels = orientShareLevels(plan);
  return { ...plan, levels, fit: fitText(plan, levels) };
}

export function EquityResearch({ slide, plan }: { slide: string; plan: Plan | undefined }) {
  if (!plan) {
    return <p className="mt-6 text-sm text-faint" data-testid="equity-empty">Equity research is not on this snapshot.</p>;
  }
  const resolved = resolvePlanLevels(plan);
  return (
    <section className="research-mode-stage mt-4" data-testid="equity-research" data-slide={slide}>
      {slide === "equity_technical" && <Technical plan={resolved} />}
      {slide === "equity_sentiment" && <Sentiment plan={resolved} />}
      {slide === "equity_fundamentals" && <Fundamentals plan={resolved} />}
      {slide === "equity_risk" && <Risk plan={resolved} />}
      {slide === "equity_scores" && <Scores plan={resolved} />}
      {slide === "equity_plan" && <TradePlan plan={resolved} />}
    </section>
  );
}

function Technical({ plan }: { plan: Plan }) {
  const confirmed = plan.confirmed_patterns ?? [];
  const developing = plan.developing_patterns ?? [];
  return (
    <section className="sf-stage" data-testid="equity-technical">
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Technical evidence</h1>
          <p className="sf-sub">As of {plan.as_of || "the snapshot"} · {plan.quote_session || "reference"} price</p>
        </div>
      </header>
      <div className="sf-split">
        <article className="sf-panel">
          <h2>Confirmed</h2>
          {confirmed.length === 0 ? <p className="sf-empty-inline">No confirmed pattern cleared the strength floor.</p> : (
            <ul className="sf-history">
              {confirmed.map((row) => (
                <li key={`${row.name}-${row.direction}`}><span>{row.name}</span><span>{row.direction}</span><span>{row.strength ?? "—"}</span></li>
              ))}
            </ul>
          )}
        </article>
        <article className="sf-panel">
          <h2>Developing</h2>
          {developing.length === 0 ? <p className="sf-empty-inline">No developing pattern is shown.</p> : (
            <ul className="sf-history">
              {developing.map((row) => (
                <li key={`${row.name}-${row.direction}`}><span>{row.name}</span><span>{row.direction}</span><span>Not confirmed</span></li>
              ))}
            </ul>
          )}
        </article>
      </div>
      <article className="sf-panel">
        <h2>Evidence</h2>
        <ul className="sf-history">
          {(plan.technical_evidence ?? []).map((line) => (
            <li key={line}><span>{line}</span></li>
          ))}
          {(plan.technical_evidence ?? []).length === 0 ? <li className="sf-empty-inline">—</li> : null}
        </ul>
        {plan.volume ? (
          <p className="sf-panel-note" data-testid="equity-volume">
            Volume regime {plan.volume.regime || "unavailable"}
            {plan.volume.ratio != null ? ` · last bar is ${plan.volume.ratio}× the recent average` : ""}
          </p>
        ) : null}
      </article>
    </section>
  );
}

function Sentiment({ plan }: { plan: Plan }) {
  const news = plan.news ?? [];
  return (
    <div data-testid="equity-sentiment">
      <h2 className="font-display text-2xl">Sentiment</h2>
      <p className="mt-2 text-sm text-faint">Company headlines only. Options flow, social posts, and order flow are not part of this score.</p>
      <p className="mt-3 text-sm">Sentiment score {score(plan.scores?.sentiment)}</p>
      {news.length === 0 ? (
        <p className="mt-4 text-sm" data-testid="equity-news-empty">No recent headlines were returned. That is left blank, not scored as neutral.</p>
      ) : (
        <ul className="mt-4 space-y-3 text-sm">
          {news.map((row) => (
            <li key={`${row.headline}-${row.published}`}>
              <p>{row.headline}</p>
              <p className="text-faint">
                {row.source || "Source unavailable"}
                {row.published ? ` · ${row.published}` : ""}
                {row.url ? (
                  <>
                    {" · "}
                    <a href={row.url} target="_blank" rel="noreferrer">Source</a>
                  </>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Fundamentals({ plan }: { plan: Plan }) {
  return (
    <div data-testid="equity-fundamentals">
      <h2 className="font-display text-2xl">Fundamentals</h2>
      <p className="mt-2 text-sm text-faint">
        {plan.instrument === "etf"
          ? "This symbol is treated as a fund. Company financial statements are not invented for it."
          : "Figures are the ones already on the fundamentals feed. A missing metric stays unavailable."}
      </p>
      <p className="mt-3 text-sm">Fundamental score {score(plan.scores?.fundamental)}</p>
      <ul className="mt-4 space-y-2 text-sm">
        {(plan.fundamentals_notes ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {plan.consensus?.status === "live" ? (
        <p className="mt-4 text-sm">
          Street consensus {plan.consensus.label || "unavailable"}
          {plan.consensus.price_target != null ? ` · target ${money(plan.consensus.price_target)}` : ""}
          {plan.consensus.source ? ` · ${plan.consensus.source}` : ""}
        </p>
      ) : (
        <p className="mt-4 text-sm">Consensus target unavailable.</p>
      )}
    </div>
  );
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function dollars(value: number | null | undefined): string {
  const amount = finite(value);
  if (amount == null) return "";
  return `$${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

type Picture = {
  price: number | null;
  atr: number | null;
  atrPct: number | null;
  stop: number | null;
  target: number | null;
  reward: number | null;
  support: number | null;
  resistance: number | null;
  spreadPct: number | null;
  risk: number | null;
};

function picture(plan: Plan): Picture {
  const market = plan.market;
  const levels = plan.levels;
  const price = finite(market?.price) ?? finite(levels?.entry);
  const stop = finite(levels?.stop);
  const storedAtr = finite(market?.atr);
  const derived = storedAtr == null && price != null && stop != null && /average true range/i.test(levels?.stop_basis || "");
  const atr = storedAtr ?? (derived ? Math.abs(price - stop) : null);
  const atrPct = finite(market?.atr_pct) ?? (atr != null && price && price > 0 ? (atr / price) * 100 : null);
  return {
    price,
    atr,
    atrPct,
    stop,
    target: finite(levels?.take_profit),
    reward: finite(levels?.reward_risk),
    support: finite(market?.support),
    resistance: finite(market?.resistance),
    spreadPct: finite(market?.spread_pct),
    risk: finite(plan.scores?.risk),
  };
}

function earningsCopy(plan: Plan): string {
  const earnings = plan.earnings;
  if (!earnings?.date) return "No earnings date is on this feed. The event is not treated as a reason to stop, and it is not invented.";
  const today = new Date().toISOString().slice(0, 10);
  if (earnings.date < today) {
    return `Earnings passed on ${earnings.date}. The date is history, not a countdown, and it does not change the action.`;
  }
  if (earnings.inside_holding_window) {
    return `Earnings on ${earnings.date} fall inside the holding window. This plan does not trade through the event, so the action is Avoid.`;
  }
  return `Next earnings are ${earnings.date}. The date sits outside the holding window, so it does not change the action.`;
}

function earningsSource(plan: Plan): string {
  if (!plan.earnings?.source) return "The calendar did not name a publisher.";
  const source = presentSource(plan.earnings.source);
  return source.url ? `${source.label}. The original page is linked from the calendar feed.` : source.label;
}

function rangeParagraph(plan: Plan): string {
  const view = picture(plan);
  if (view.atr != null && view.atrPct != null && view.price != null) {
    const band = view.atrPct <= 2
      ? "at or under 2% of price, so the advisory score starts at 80"
      : view.atrPct <= 4
        ? "between 2% and 4% of price, so the advisory score starts at 60"
        : "wider than 4% of price, so the advisory score starts at 40";
    return `Over the last 14 bars the share typically travels ${dollars(view.atr)}, or ${view.atrPct.toFixed(2)}% of the ${dollars(view.price)} reference. That is ${band}. A tight range makes a closer stop usable. A wide range means the same stop is more likely to be touched by ordinary trade.`;
  }
  if (view.price != null && view.risk != null) {
    const low = dollars(view.price * 0.02);
    const high = dollars(view.price * 0.04);
    if (view.risk >= 70) return `The exact 14-bar range was not stored as its own figure. A score of ${view.risk.toFixed(1)} means the recent range is about ${low} or less, no more than 2% of ${dollars(view.price)}.`;
    if (view.risk >= 50) return `The exact 14-bar range was not stored as its own figure. A score of ${view.risk.toFixed(1)} means the recent range is about ${low} to ${high}, between 2% and 4% of ${dollars(view.price)}. That is ordinary movement: wide enough to respect, not wide enough to call the name unstable.`;
    if (view.risk >= 30) return `The exact 14-bar range was not stored as its own figure. A score of ${view.risk.toFixed(1)} means the recent range is wider than ${high}, more than 4% of ${dollars(view.price)}, or a penalty has already been taken off a quieter band.`;
  }
  if (view.price != null) return `The reference price is ${dollars(view.price)}. The range is read from the stop distance when the stop uses the 14-bar average true range.`;
  return "The reference price is the last snapshot price. The range is the 14-bar average true range, expressed in dollars and as a percent of that price.";
}

function levelParagraph(plan: Plan): string {
  const view = picture(plan);
  const action = plan.action || "This reading";
  if (view.stop == null || view.target == null) {
    const ref = view.price != null ? ` The reference price stays ${dollars(view.price)}.` : "";
    return `${action} uses ${ref ? dollars(view.price) : "the snapshot price"} as the reference. The stop sits one range beyond that price and the take-profit is two times that distance. ${plan.levels?.exit_note || ""}`.trim();
  }
  const riskDist = view.price != null ? Math.abs(view.price - view.stop) : null;
  const multiple = view.reward != null
    ? view.reward.toFixed(2)
    : view.price != null && riskDist
      ? (Math.abs(view.target - view.price) / riskDist).toFixed(2)
      : null;
  const near = (left: number | null, right: number | null) => left != null && right != null && Math.abs(left - right) < 0.05;
  let structure = "A separate swing high and swing low were not stored, so the take-profit is the payoff multiple of the stop distance.";
  if (view.support != null && view.resistance != null) {
    const usesLevel = near(view.target, view.resistance) || near(view.target, view.support);
    structure = `The recent swing low is ${dollars(view.support)} and the recent swing high is ${dollars(view.resistance)}. ${usesLevel ? "The take-profit uses that swing level." : "The take-profit stays at two times the risk, because that swing level is not at least one full range beyond the reference."}`;
  }
  const basis = plan.levels?.stop_basis ? ` The stop is the ${plan.levels.stop_basis}.` : "";
  return `From ${dollars(view.price) || "the reference"} the stop is ${dollars(view.stop)} and the take-profit is ${dollars(view.target)}.${riskDist != null ? ` The risk is ${dollars(riskDist)}.` : ""}${multiple ? ` The target pays ${multiple} dollars for each dollar of risk.` : ""}${basis} ${structure}`;
}

function penaltyParagraph(plan: Plan): string {
  const view = picture(plan);
  const earningsHit = Boolean(plan.earnings?.inside_holding_window);
  const event = earningsHit
    ? "Earnings fall inside the holding window, so 25 points come off the advisory score and the plan does not trade the event."
    : "Earnings are outside the holding window, or already passed, so the 25-point event penalty does not apply.";
  const spread = view.spreadPct == null
    ? "Both sides of the quote were not on this snapshot, so the 10-point spread penalty was not applied."
    : view.spreadPct > 1
      ? `The bid/ask is ${view.spreadPct.toFixed(2)}% of price, wider than 1%, so 10 points come off.`
      : `The bid/ask is ${view.spreadPct.toFixed(2)}% of price, inside 1%, so the quote does not change the score.`;
  const result = view.risk != null
    ? ` The advisory score is ${view.risk.toFixed(1)}. It records the range and those penalties. It is not added to the weighted figure, and it is not a probability of profit.`
    : " The advisory score records the range, then those two penalties. It is not added to the weighted figure.";
  return `${event} ${spread}${result}`;
}

function volumeParagraph(plan: Plan): string {
  const volume = plan.volume;
  if (volume?.ratio == null && !volume?.regime) {
    return "Share volume was not attached, so it does not change this risk score. On the scorecard, a missing volume ratio is left off rather than marked as average.";
  }
  const ratio = volume.ratio != null ? ` The last bar is ${volume.ratio}× the recent average${typeof volume.average === "number" ? ` of ${Math.round(volume.average).toLocaleString()} shares` : ""}.` : "";
  const meaning = volume.ratio == null
    ? ""
    : volume.ratio >= 1.2
      ? " Participation is active. On the scorecard that can score 2 for the side aligned with the trend, and 0 against it."
      : volume.ratio < 0.8
        ? " Participation is quiet. On the scorecard that scores 0, because the move is not being confirmed by volume."
        : " Participation is ordinary. On the scorecard that scores 1, a middle reading rather than a strong confirmation.";
  return `Volume is ${volume.regime || "recorded"}.${ratio} ${meaning}`.trim();
}

function profileParagraph(plan: Plan): string {
  const name = (plan.risk_profile || "moderate").toLowerCase();
  const reward = picture(plan).reward;
  if (name === "conservative") {
    const fit = reward == null
      ? "This action does not publish a payoff multiple, so the 2-for-1 rule is not being failed by a missing number."
      : reward >= 2
        ? `This plan pays ${reward.toFixed(2)}, which clears that rule.`
        : `This plan pays ${reward.toFixed(2)}, which is below 2, so the action is Avoid.`;
    return `The saved profile is conservative. A buy must pay at least 2 dollars of target for each dollar of risk. ${fit}`;
  }
  if (name === "aggressive") {
    return "The saved profile is aggressive. The scorecard is the gate. The extra rule that demands 2 dollars of target per dollar of risk is not applied.";
  }
  return "The saved profile is moderate. The scorecard is the gate. The extra conservative payoff rule is not applied.";
}

function atrCell(plan: Plan): string {
  const view = picture(plan);
  if (view.atr != null && view.atrPct != null) return `${dollars(view.atr)} · ${view.atrPct.toFixed(2)}% of price`;
  if (view.price != null && view.risk != null && view.risk >= 50 && view.risk < 70) {
    return `${dollars(view.price * 0.02)} to ${dollars(view.price * 0.04)} · the 2% to 4% band for this score`;
  }
  if (view.stop != null && view.price != null) return `${dollars(Math.abs(view.price - view.stop))} · the distance from the reference to the stop`;
  return "Read from the 14-bar average true range once the bars are on the snapshot";
}

function swingCell(value: number | null, role: "low" | "high", plan: Plan): string {
  if (value != null) return `${dollars(value)} · recent swing ${role}`;
  const view = picture(plan);
  if (role === "low") return view.stop != null ? `The swing low is not stored. The protective level in use is the stop at ${dollars(view.stop)}.` : `The protective level is one range below ${dollars(view.price) || "the reference"}.`;
  return view.target != null ? `The swing high is not stored. The objective in use is the take-profit at ${dollars(view.target)}.` : `The objective is two times the distance from ${dollars(view.price) || "the reference"} to the stop.`;
}

function Risk({ plan }: { plan: Plan }) {
  const view = picture(plan);
  return (
    <section className="sf-stage" data-testid="equity-risk">
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Risks and volatility</h1>
          <p className="sf-sub">How far the share usually moves, and whether that still leaves a usable stop and target</p>
        </div>
      </header>
      <div className="sf-split">
        <article className="sf-panel">
          <h2>Range and the plan</h2>
          <p className="sf-panel-note">{rangeParagraph(plan)}</p>
          <p className="sf-panel-note">{levelParagraph(plan)}</p>
          <dl className="sf-kv">
            <div><dt>Risk score</dt><dd>{view.risk != null ? `${view.risk.toFixed(1)} · advisory only, not part of the weighted total` : "Recorded from the range once price and the 14-bar move are both present"}</dd></div>
            <div><dt>Reference price</dt><dd>{view.price != null ? `${dollars(view.price)} · the snapshot used for the stop and the target` : "The last traded price on the snapshot"}</dd></div>
            <div><dt>Average true range</dt><dd>{atrCell(plan)}</dd></div>
            <div><dt>Support</dt><dd>{swingCell(view.support, "low", plan)}</dd></div>
            <div><dt>Resistance</dt><dd>{swingCell(view.resistance, "high", plan)}</dd></div>
            <div><dt>Stop</dt><dd>{view.stop != null && view.price != null && view.stop > view.price ? `${dollars(view.stop)} · above the entry, because a rise through it ends the downside case` : view.stop != null ? `${dollars(view.stop)} · below the entry, because a drop through it ends the upside case` : `${dollars(view.price)} minus one range`}</dd></div>
            <div><dt>Take profit</dt><dd>{view.target != null && view.price != null && view.target < view.price ? `${dollars(view.target)} · below the entry, because that is the lower objective` : view.target != null ? `${dollars(view.target)} · above the entry, because that is the higher objective` : "Two times the distance from the reference to the stop"}</dd></div>
            <div><dt>Reward / risk</dt><dd>{view.reward != null ? `${view.reward.toFixed(2)} · dollars of target for each dollar of risk` : "Not published when this action has no stop and target"}</dd></div>
          </dl>
        </article>
        <article className="sf-panel">
          <h2>What changes the score</h2>
          <p className="sf-panel-note">{penaltyParagraph(plan)}</p>
          <p className="sf-panel-note">{volumeParagraph(plan)}</p>
          <p className="sf-panel-note">{profileParagraph(plan)}</p>
          <dl className="sf-kv">
            <div><dt>Earnings</dt><dd>{earningsCopy(plan)}</dd></div>
            <div><dt>Confirmed</dt><dd>{plan.earnings?.date ? (plan.earnings.confirmed ? "Yes. The date is on the calendar feed." : "A date is present and is not marked confirmed.") : "No date is on the feed, so nothing is confirmed or denied."}</dd></div>
            <div><dt>Inside holding window</dt><dd>{plan.earnings?.inside_holding_window ? "Yes. That is why the plan does not trade it." : "No. A passed date or a later date stays outside the hold."}</dd></div>
            <div><dt>Source</dt><dd>{earningsSource(plan)}</dd></div>
            <div><dt>Risk profile</dt><dd>{(plan.risk_profile || "moderate").replace(/^./, (letter) => letter.toUpperCase())}</dd></div>
          </dl>
          <p className="sf-panel-note">{plan.short_note || "Borrow availability is not on this feed, so a short sale is not recommended."}</p>
        </article>
      </div>
    </section>
  );
}

function scoreGaugeOffset(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 126;
  return 126 * (1 - Math.max(0, Math.min(100, value)) / 100);
}

const POINT_LABELS: Record<string, string> = {
  structure: "Structure",
  trend: "Trend",
  volume: "Volume",
  fundamentals: "Fundamentals",
  catalyst: "Catalyst",
  sentiment: "Sentiment",
  market: "Market",
  sector: "Sector",
};

function shown(value: number | null | undefined): string {
  return finite(value) == null ? "Left out" : finite(value)!.toFixed(1);
}

function quality(value: number): string {
  if (value >= 80) return "strong";
  if (value >= 70) return "solid";
  if (value >= 55) return "modest";
  return "soft";
}

function contributionRow(plan: Plan, layer: string) {
  return (plan.scores?.contributions ?? []).find((item) => item.layer === layer);
}

function addedLine(plan: Plan, layer: string, weighted: boolean): string {
  const row = contributionRow(plan, layer);
  if (row && typeof row.points === "number") {
    return `+${row.points.toFixed(1)} points · ${Math.round(row.weight * 100)}% of ${row.score.toFixed(1)}`;
  }
  if (!weighted) return "Not included in the weighted figure";
  if ((plan.scores?.reweighted ?? []).includes(layer)) return "Left out, and the other weights are scaled to 100%";
  return "Included at its display weight";
}

function weightLabel(plan: Plan, layer: string, fallback: string): string {
  const row = contributionRow(plan, layer);
  if (row && typeof row.points === "number") return `${Math.round(row.weight * 100)}% · +${row.points.toFixed(1)}`;
  if ((plan.scores?.reweighted ?? []).includes(layer)) return "Left out";
  return fallback;
}

function gateLine(side: string, card: { earned?: number; possible?: number; passes?: boolean } | undefined): string {
  if (card?.earned == null || card.possible == null) return `${side} card is carried on the scan when the scorecard is present.`;
  const gate = Math.round((11 / 16) * card.possible);
  const clears = card.passes ?? card.earned >= gate;
  return `${side} card ${card.earned} of ${card.possible}. The gate on a ${card.possible}-point card is ${gate}, the same 11-of-16 standard scaled to the components that were actually scored. ${clears ? "It clears." : "It does not clear."}`;
}

function cardLine(plan: Plan, keys: string[]): string {
  const bull = plan.scorecard?.bull?.points;
  const bear = plan.scorecard?.bear?.points;
  if (!bull && !bear) return "Each component is 0, 1, or 2. A missing component is left off the card.";
  return keys.map((key) => {
    const name = POINT_LABELS[key] || key;
    const left = bull?.[key];
    const right = bear?.[key];
    if (left == null && right == null) return `${name} is left off the card rather than filled in as a middle score.`;
    const word = (value: number | null | undefined) => value == null ? "left off" : value >= 2 ? "2, aligned" : value === 1 ? "1, mixed" : "0, opposed";
    return `${name} is ${word(left)} on the bullish card and ${word(right)} on the bearish card.`;
  }).join(" ");
}

function signedSentence(display: number): string {
  const signed = display * 2 - 100;
  const printed = `${signed >= 0 ? "+" : ""}${signed.toFixed(1)}`;
  const lean = signed >= 20
    ? "That is at or above +20, so the bullish card can take the constructive sentiment point and the bearish card does not."
    : signed <= -20
      ? "That is at or below -20, so the bearish card can take the negative sentiment point and the bullish card does not."
      : "That sits between -20 and +20, so both cards mark sentiment as mixed.";
  return `A flat headline tape is 0 and displays as 50. This ${display.toFixed(1)} is a signed tone of about ${printed}. ${lean}`;
}

function mathSentence(plan: Plan): string {
  const rows = plan.scores?.contributions ?? [];
  if (rows.length) {
    return rows.map((row) => `${POINT_LABELS[row.layer] || row.layer} adds ${row.points.toFixed(1)}`).join(", ") + ".";
  }
  const dropped = plan.scores?.reweighted ?? [];
  if (dropped.length) return `${dropped.join(" and ")} ${dropped.length === 1 ? "is" : "are"} left out, and the remaining weights are scaled to 100%.`;
  return "The figure is the technical score at 60%, the fundamental score at 25%, and the sentiment score at 15%.";
}

function Scores({ plan }: { plan: Plan }) {
  const overall = finite(plan.scores?.overall);
  const tier = scoreTier(overall);
  const [open, setOpen] = useState<Record<string, boolean>>({
    technical: true,
    sentiment: true,
    fundamental: true,
    risk: true,
  });
  const technical = finite(plan.scores?.technical);
  const sentiment = finite(plan.scores?.sentiment);
  const fundamental = finite(plan.scores?.fundamental);
  const patterns = (plan.confirmed_patterns ?? []).map((row) => row.name).filter(Boolean);
  const evidence = (plan.technical_evidence ?? []).filter(Boolean);
  const notes = (plan.fundamentals_notes ?? []).filter(Boolean);
  const headlines = plan.news ?? [];
  const sections = [
    {
      id: "technical",
      title: "Technical",
      value: technical,
      weight: weightLabel(plan, "technical", "60%"),
      narrative: technical == null
        ? "Technicals are the largest input, 60% of the weighted figure, the midpoint of the masterbook's 50–70 range. This snapshot does not have a technical score, so the other pillars are scaled and this one is not filled in as 50."
        : `The technical score is ${technical.toFixed(1)}, a ${quality(technical)} chart reading. It is 60% of the weighted figure, the midpoint of the masterbook's 50–70 range, so it leads the gauge. Confirmed patterns and the trend of the bars are what it reads. A developing pattern can be seen on the technical slide and does not count as confirmed.`,
      detail: [
        evidence[0] || "The chart narrative is the trend, the EMA stack, and whether a confirmed pattern cleared the strength floor.",
        patterns.length ? `Confirmed patterns: ${patterns.join(", ")}.` : "No confirmed pattern cleared the strength floor, so the score is coming from the trend and the indicator stack.",
        cardLine(plan, ["structure", "trend", "volume"]),
      ],
      rows: [
        ["Score", technical == null ? "Left out of this total" : `${technical.toFixed(1)} · ${quality(technical)}`],
        ["Weight", "60% of the weighted figure"],
        ["Added to the total", addedLine(plan, "technical", true)],
        ["What would weaken it", "A lost trend, a failed pattern, or volume that no longer agrees with the direction"],
      ],
    },
    {
      id: "sentiment",
      title: "Sentiment",
      value: sentiment,
      weight: weightLabel(plan, "sentiment", "15%"),
      narrative: sentiment == null
        ? "Sentiment is 15% of the weighted figure, the midpoint of the 10–20 range. No company headlines were scored, so this pillar is left out and the technical and fundamental weights are scaled. It is not filled in as a neutral 50."
        : `The sentiment score is ${sentiment.toFixed(1)}, a ${quality(sentiment)} headline reading, and it is 15% of the weighted figure. ${signedSentence(sentiment)} Options flow, social posts, and order flow are not in this number.`,
      detail: [
        headlines.length
          ? `${headlines.length} company headline${headlines.length === 1 ? "" : "s"} on this snapshot. The first is “${headlines[0]?.headline}”.`
          : "No headline is attached. The pillar stays out of the total until a company headline feed returns a score.",
        cardLine(plan, ["sentiment"]),
      ],
      rows: [
        ["Score", sentiment == null ? "Left out of this total" : `${sentiment.toFixed(1)} · ${quality(sentiment)} headline tone`],
        ["Weight", "15% of the weighted figure"],
        ["Added to the total", addedLine(plan, "sentiment", true)],
        ["What it can do", "Support or oppose the card. At 15% it cannot carry the gauge by itself."],
      ],
    },
    {
      id: "fundamental",
      title: "Fundamental",
      value: fundamental,
      weight: weightLabel(plan, "fundamental", "25%"),
      narrative: fundamental == null
        ? "Fundamentals are 25% of the weighted figure, the midpoint of the 20–35 range. This snapshot has no company score, so the pillar is left out. A fund is not given invented financial statements."
        : `The fundamental score is ${fundamental.toFixed(1)}, a ${quality(fundamental)} company reading. It is 25% of the weighted figure, the midpoint of the 20–35 range. It can confirm a chart lead. It does not replace the stop or the take-profit.`,
      detail: [
        notes[0] || "The company feed covers growth, earnings quality, and the street target when those figures are present.",
        notes[1] || "A street target is context for the business. It is not this trade's take-profit.",
        cardLine(plan, ["fundamentals", "catalyst"]),
      ],
      rows: [
        ["Score", fundamental == null ? "Left out of this total" : `${fundamental.toFixed(1)} · ${quality(fundamental)}`],
        ["Weight", "25% of the weighted figure"],
        ["Added to the total", addedLine(plan, "fundamental", true)],
        ["Street target", plan.consensus?.status === "live" && plan.consensus.price_target != null ? `${dollars(plan.consensus.price_target)} · context, not the trade objective` : "Shown only when the street feed returns a live target"],
      ],
    },
    {
      id: "risk",
      title: "Risk / volatility",
      value: finite(plan.scores?.risk),
      weight: "Advisory",
      narrative: "Risk is kept beside the gauge and out of the arithmetic on purpose. A wide range is a fact about the share's movement. Putting it inside the weighted figure would make a quiet stock look like a better business.",
      detail: [rangeParagraph(plan), penaltyParagraph(plan), profileParagraph(plan)],
      rows: [
        ["Score", finite(plan.scores?.risk) == null ? "Recorded once the range is known" : `${finite(plan.scores?.risk)!.toFixed(1)} · advisory`],
        ["Weight", "Not included"],
        ["Added to the total", "0. The gauge ignores this score."],
        ["What it changes", "The stop distance, the event penalty, and whether a conservative profile still has 2 dollars of target per dollar of risk"],
      ],
    },
  ];
  return (
    <section className="sf-stage as-stage" data-testid="equity-scores" data-tier={tier}>
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Layer scores</h1>
          <p className="sf-sub">Equity assessment · the weighted figure is not a probability of profit</p>
        </div>
      </header>
      <div className="as-hero">
        <div className="sf-gauge as-composite-gauge" data-testid="equity-overall" aria-label={`Overall assessment ${shown(overall)}`}>
          <svg viewBox="0 0 120 70" className="sf-gauge-svg">
            <path d="M10 60 A50 50 0 0 1 110 60" className="sf-gauge-track" />
            <path
              d="M10 60 A50 50 0 0 1 110 60"
              className={`sf-gauge-fill as-gauge-fill is-${tier}`}
              strokeDasharray="126"
              strokeDashoffset={scoreGaugeOffset(overall)}
            />
          </svg>
          <p className={`as-composite-value is-${tier}`}>{shown(overall)}</p>
          <p className="as-composite-label">/ 100</p>
        </div>
        <div className="as-hero-copy">
          <p className="as-threshold-badge is-below" data-testid="equity-scorecard">
            Bullish card {plan.scorecard?.bull?.earned ?? "—"} / {plan.scorecard?.bull?.possible ?? "—"} · Bearish card {plan.scorecard?.bear?.earned ?? "—"} / {plan.scorecard?.bear?.possible ?? "—"}
          </p>
          <p className="as-section-narrative">
            {overall == null ? "The weighted reading needs at least one scored pillar." : `${overall.toFixed(1)} is the weighted equity reading. ${mathSentence(plan)} It is not a probability of profit.`}
          </p>
          <p className="as-section-narrative">{gateLine("Bullish", plan.scorecard?.bull)} {gateLine("Bearish", plan.scorecard?.bear)}</p>
          <p className="as-section-interpretation">
            {plan.action ? `This snapshot's plan is ${plan.action}. ${plan.why || ""}` : plan.weight_policy} The gauge does not place the order. The scorecard does.
          </p>
        </div>
      </div>
      <div className="as-sections">
        {sections.map((section) => {
          const isOpen = Boolean(open[section.id]);
          return (
            <div key={section.id} className="as-section" data-testid={`equity-score-${section.id}`}>
              <button
                type="button"
                className="as-section-head w-full text-left"
                aria-expanded={isOpen}
                onClick={() => setOpen((prev) => ({ ...prev, [section.id]: !prev[section.id] }))}
              >
                <span className="as-section-title">{section.title}</span>
                <span className="as-section-score">{shown(section.value)}</span>
                <span className="as-section-weight">{section.weight}</span>
                <span aria-hidden className="text-bronze">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen ? (
                <div className="as-section-body">
                  <p className="as-section-narrative">{section.narrative}</p>
                  {section.detail.map((line) => (
                    <p key={line} className="as-section-interpretation">{line}</p>
                  ))}
                  <dl className="sf-kv as-breakdown">
                    {section.rows.map(([label, value]) => (
                      <div key={label} className="as-breakdown-row">
                        <dt>{label}</dt>
                        <dd><span className="as-breakdown-value">{value}</span></dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function TradePlan({ plan }: { plan: Plan }) {
  const levels = plan.levels;
  return (
    <section className="sf-stage" data-testid="equity-plan">
      <header className="sf-head">
        <div>
          <h1 className="sf-title">Recommendation</h1>
          <p className="sf-sub" data-testid="equity-action">{plan.action}</p>
        </div>
      </header>
      <article className="sf-panel">
        <h2>Why this fits</h2>
        <p className="sf-panel-note" data-testid="equity-fit">{plan.fit}</p>
        <p className="sf-panel-note">{plan.why}</p>
        <p className="sf-panel-note">Holding horizon: {plan.horizon?.label}. {plan.horizon?.detail}</p>
        <dl className="sf-kv">
          <div><dt>{plan.action === "Sell" ? "Exit" : "Entry"}</dt><dd>{money(levels?.entry)}</dd></div>
          <div><dt>Stop</dt><dd>{money(levels?.stop)}</dd></div>
          <div><dt>Take profit</dt><dd>{money(levels?.take_profit)}</dd></div>
          <div><dt>Reward / risk</dt><dd>{levels?.reward_risk ?? "—"}</dd></div>
        </dl>
        <p className="sf-panel-note">{levels?.entry_label}</p>
        <p className="sf-panel-note">{levels?.exit_note}</p>
        {levels?.stop_basis ? <p className="sf-panel-note">Stop basis: {levels.stop_basis}.</p> : null}
      </article>
      <Analysts plan={plan} />
    </section>
  );
}

function Analysts({ plan }: { plan: Plan }) {
  const rows = plan.analysts ?? [];
  if (!rows.length) return null;
  return (
    <article className="sf-panel" data-testid="equity-analysts">
      <h2>{plan.analyst_basis || "Analyst ratings"}</h2>
      <p className="mt-2 text-sm text-faint">{plan.analyst_note}</p>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm">No named analyst ratings were returned.</p>
      ) : (
        <ul className="mt-3 space-y-3 text-sm">
          {rows.map((row) => (
            <li key={`${row.firm}-${row.analyst}-${row.date}`}>
              <p>{row.analyst || "Analyst name unavailable"} · {row.firm || "Firm unavailable"}</p>
              <p className="text-faint">
                {row.rating}
                {row.price_target != null ? ` · target ${money(row.price_target)} ${row.currency || ""}` : ""}
                {row.date ? ` · ${row.date}` : " · date unavailable"}
                {row.source ? ` · ${row.source}` : ""}
                {row.url ? (
                  <>
                    {" · "}
                    <a href={row.url} target="_blank" rel="noreferrer">Source</a>
                  </>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
