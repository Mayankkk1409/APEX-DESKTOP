/** Share levels follow the stronger case. Upside: stop below, target above. Downside: stop above, target below. */

export type ShareLevels = {
  entry?: number | null;
  stop?: number | null;
  take_profit?: number | null;
  exit_target?: number | null;
  reward_risk?: number | null;
  stop_basis?: string | null;
  entry_label?: string | null;
  exit_note?: string | null;
};

export type LevelContext = {
  action?: string;
  trend?: string;
  holds_shares?: boolean;
  levels?: ShareLevels | null;
  market?: {
    price?: number | null;
    atr?: number | null;
    support?: number | null;
    resistance?: number | null;
  } | null;
  scorecard?: {
    bull?: { earned?: number; possible?: number; passes?: boolean };
    bear?: { earned?: number; possible?: number; passes?: boolean };
  };
};

function num(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function bestDirection(plan: LevelContext): "long" | "down" {
  const bull = plan.scorecard?.bull;
  const bear = plan.scorecard?.bear;
  if (bull?.passes && !bear?.passes) return "long";
  if (bear?.passes && !bull?.passes) return "down";
  const bullPts = bull?.earned ?? 0;
  const bearPts = bear?.earned ?? 0;
  if (bearPts > bullPts) return "down";
  if (bullPts > bearPts) return "long";
  if (plan.trend === "down") return "down";
  return "long";
}

function matches(direction: "long" | "down", price: number, stop: number, target: number): boolean {
  return direction === "long" ? stop < price && target > price : stop > price && target < price;
}

export function orientShareLevels(plan: LevelContext): ShareLevels {
  const source = plan.levels ?? {};
  const price = num(plan.market?.price) ?? num(source.entry);
  const stop = num(source.stop);
  const target = num(source.take_profit);
  const direction = bestDirection(plan);
  if (price != null && stop != null && target != null && matches(direction, price, stop, target)) {
    return source;
  }
  if (price == null || price <= 0) return source;
  const atr = num(plan.market?.atr);
  const risk = atr != null && atr > 0 ? atr : stop != null ? Math.abs(price - stop) : price * 0.02;
  const support = num(plan.market?.support);
  const resistance = num(plan.market?.resistance);
  const nextStop = direction === "down" ? round2(price + risk) : round2(Math.max(0.01, price - risk));
  const nextTarget = direction === "down"
    ? (support != null && support < price - risk ? round2(support) : round2(price - 2 * risk))
    : (resistance != null && resistance > price + risk ? round2(resistance) : round2(price + 2 * risk));
  const riskAmt = Math.abs(price - nextStop);
  return {
    ...source,
    entry: num(source.entry) ?? round2(price),
    stop: nextStop,
    take_profit: nextTarget,
    exit_target: nextTarget,
    reward_risk: riskAmt > 0 ? round2(Math.abs(nextTarget - price) / riskAmt) : null,
    stop_basis: source.stop_basis || (atr != null && atr > 0 ? "14-bar average true range" : "2% of price"),
  };
}

export function fitText(plan: LevelContext, levels: ShareLevels): string {
  const direction = bestDirection(plan);
  const entry = num(levels.entry);
  const stop = num(levels.stop);
  const target = num(levels.take_profit);
  const reward = num(levels.reward_risk);
  const bull = plan.scorecard?.bull;
  const bear = plan.scorecard?.bear;
  const cards = bull?.earned != null && bear?.earned != null
    ? `The bullish card is ${bull.earned} of ${bull.possible ?? "—"}. The bearish card is ${bear.earned} of ${bear.possible ?? "—"}. `
    : "";
  const payoff = reward != null ? ` The target pays ${reward.toFixed(2)} dollars for each dollar of risk.` : "";
  if (entry == null || stop == null || target == null) {
    return `${cards}The levels use one range of risk and a target twice that far, on the side the evidence supports.`;
  }
  if (direction === "down") {
    const order = plan.holds_shares || plan.action === "Sell"
      ? " The account already holds shares, so the order that matches this case is a sale of those shares."
      : " Borrow is not on this feed, so no short sale is sent. These levels are still the downside case, because that is the side that fits.";
    return (
      `${cards}The downside case is the one that fits. It pays if the share falls from ${entry.toFixed(2)}. ` +
      `The stop at ${stop.toFixed(2)} is above the entry, because a rise through it means the decline failed. ` +
      `The take-profit at ${target.toFixed(2)} is below the entry, because that is the lower objective.${payoff}${order}`
    );
  }
  return (
    `${cards}The upside case is the one that fits. It pays if the share rises from ${entry.toFixed(2)}. ` +
    `The stop at ${stop.toFixed(2)} is below the entry, because a drop through it means the rise failed. ` +
    `The take-profit at ${target.toFixed(2)} is above the entry, because that is the higher objective.${payoff}`
  );
}
