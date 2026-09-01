/**
 * Chain-table layout for the combined options + Greeks screen.
 *
 * The backend owns the §5 rule verdicts; this module owns presentation only — pairing
 * calls and puts onto one strike row, locating ATM, classifying ITM/OTM, and formatting.
 * Nothing here invents a value: a missing datum formats as an em dash.
 */
import type { ChainAnalysis, ChainContractRow, ContractVerdict, RecommendedContract } from "../types";

export type ChainLadderRow = {
  strike: number;
  call: ChainContractRow | null;
  put: ChainContractRow | null;
  /** True when this strike row carries the server-recommended contract leg. */
  isRecommended: boolean;
  recommendedSide: "call" | "put" | null;
  /** Which side of this strike is in the money, for the ITM shading band. */
  itmSide: "call" | "put" | null;
  /** True when either leg is hard-rejected by the §5.5 spread gate. */
  hasReject: boolean;
  /** True when either leg fails a §5.6 liquidity gate without being hard-rejected. */
  hasGateFailure: boolean;
  hasUoa: boolean;
};

const DASH = "—";

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return Math.round(value).toLocaleString();
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** Mid of a two-sided market, or `null` when there is no market to price. */
export function midOf(bid: number | null | undefined, ask: number | null | undefined): number | null {
  if (bid === null || bid === undefined || ask === null || ask === undefined) return null;
  if (!Number.isFinite(bid) || !Number.isFinite(ask)) return null;
  if (bid <= 0 && ask <= 0) return null;
  if (ask < bid) return null;
  return (bid + ask) / 2;
}

/** Spread as a fraction of mid, or `null` when it cannot be computed. */
export function spreadPctOfMid(bid: number | null | undefined, ask: number | null | undefined): number | null {
  const mid = midOf(bid, ask);
  if (mid === null || mid <= 0 || bid === null || bid === undefined || ask === null || ask === undefined) return null;
  return (ask - bid) / mid;
}

/**
 * Strike nearest spot. `null` when there is no spot reference, because guessing an ATM
 * from the middle of the printed ladder would be a fabricated anchor.
 */
export function atmStrike(rows: { strike: number }[], spot: number | null | undefined): number | null {
  if (spot === null || spot === undefined || !Number.isFinite(spot) || spot <= 0 || !rows.length) return null;
  return rows.reduce((best, r) => (Math.abs(r.strike - spot) < Math.abs(best - spot) ? r.strike : best), rows[0].strike);
}

export function moneyness(side: "call" | "put", strike: number, spot: number | null | undefined): "itm" | "otm" | "unknown" {
  if (spot === null || spot === undefined || !Number.isFinite(spot) || spot <= 0) return "unknown";
  if (side === "call") return strike < spot ? "itm" : "otm";
  return strike > spot ? "itm" : "otm";
}

export function matchesRecommended(
  strike: number,
  side: "call" | "put",
  recommended: RecommendedContract | null | undefined,
): boolean {
  if (!recommended) return false;
  return recommended.strike === strike && recommended.side === side;
}

/**
 * Fold a flat contract list into one row per strike, calls and puts side by side.
 * Handles single-sided chains (a strike with only calls or only puts) without dropping it.
 */
export function buildLadder(
  contracts: ChainContractRow[],
  spot: number | null | undefined,
  recommended: RecommendedContract | null | undefined = null,
): ChainLadderRow[] {
  const byStrike = new Map<number, { call: ChainContractRow | null; put: ChainContractRow | null }>();
  for (const c of contracts) {
    if (!Number.isFinite(c.strike)) continue;
    const slot = byStrike.get(c.strike) ?? { call: null, put: null };
    if (c.side === "call") slot.call = c;
    else slot.put = c;
    byStrike.set(c.strike, slot);
  }
  const strikes = [...byStrike.keys()].sort((a, b) => a - b);
  return strikes.map((strike) => {
    const slot = byStrike.get(strike)!;
    const callItm = moneyness("call", strike, spot) === "itm";
    const putItm = moneyness("put", strike, spot) === "itm";
    const legs = [slot.call, slot.put].filter(Boolean) as ChainContractRow[];
    const recSide =
      (slot.call && matchesRecommended(strike, "call", recommended) && "call") ||
      (slot.put && matchesRecommended(strike, "put", recommended) && "put") ||
      null;
    return {
      strike,
      call: slot.call,
      put: slot.put,
      isRecommended: recSide !== null,
      recommendedSide: recSide,
      itmSide: callItm ? "call" : putItm ? "put" : null,
      hasReject: legs.some((l) => l.verdict?.hard_reject === true),
      hasGateFailure: legs.some((l) => l.verdict?.verdict === "screened_out"),
      hasUoa: legs.some((l) => l.verdict?.flags.includes("uoa") === true),
    };
  });
}

export const VERDICT_LABELS: Record<string, string> = {
  buy_candidate: "BUY",
  sell_candidate: "SELL",
  tradeable: "OK",
  screened_out: "GATE",
  rejected: "REJECT",
  insufficient_data: "NO DATA",
};

export const VERDICT_TITLES: Record<string, string> = {
  buy_candidate: "Clears every liquidity gate and fits the §5.1 / §5.2 buy profile",
  sell_candidate: "Clears every liquidity gate and fits the §5.1 / §5.2 short-leg profile",
  tradeable: "Clears every liquidity gate but fits no documented directional bucket",
  screened_out: "Fails a §5.6 open-interest or volume gate",
  rejected: "HARD REJECT — §5.5 bid/ask spread exceeds the configured cap of mid",
  insufficient_data: "Cannot be graded — a required quote or Greek is missing",
};

/** Short, specific reason a leg is flagged, for the table cell tooltip. */
export function gateSummary(verdict: ContractVerdict | null | undefined): string {
  if (!verdict) return "Not evaluated.";
  const failed = verdict.gates.filter((g) => g.status === "fail");
  const unknown = verdict.gates.filter((g) => g.status === "unknown");
  const warned = verdict.gates.filter((g) => g.status === "warn");
  const parts: string[] = [VERDICT_TITLES[verdict.verdict] ?? verdict.verdict];
  if (failed.length) parts.push(`Failed: ${failed.map((g) => `${g.label} (${g.observed})`).join("; ")}.`);
  if (warned.length) parts.push(`Warn: ${warned.map((g) => `${g.label} (${g.observed})`).join("; ")}.`);
  if (unknown.length) parts.push(`Unknown: ${unknown.map((g) => g.label).join(", ")}.`);
  return parts.join(" ");
}

const FLAG_LABELS: Record<string, string> = {
  uoa: "UOA",
  rule1_buy: "RULE 1",
  rule2_sell: "RULE 2",
  gamma_risk_7dte: "GAMMA 7D",
  vega_cap_blocked: "VEGA CAP",
  spread_near_cap: "WIDE",
};

/** Sentence explaining a flag that applies to the whole expiry, for the hoisted strip. */
const FLAG_CHAIN_WIDE_NOTES: Record<string, string> = {
  gamma_risk_7dte:
    "§5.4 Gamma flag applies to every strike: this expiry is inside 7 days, so Delta reprices violently on any move.",
  vega_cap_blocked:
    "§5.3 Vega cap is blocking long premium on every strike: this is a catalyst environment with no override and no Gamma Trampoline structure.",
  rule1_buy: "Every graded strike fits the §5.1 buy-side Delta profile.",
  rule2_sell: "Every graded strike fits the §5.1 short-leg Delta profile.",
  spread_near_cap: "Every strike is quoting within a whisker of the §5.5 spread cap.",
  uoa: "Every strike is printing unusual volume, which usually means an event, not a signal on one strike.",
};

/**
 * Flag ids carried by *every* graded contract on the expiry.
 *
 * Such a flag is a property of the expiry, not of a strike — 7-DTE Gamma risk and a blocking
 * Vega cap are the common cases — so the screen states it once above the ladder instead of
 * stamping an identical badge on all 34 rows, which reads as noise and hides the flags that
 * genuinely single a strike out.
 */
export function chainWideFlags(contracts: ChainContractRow[]): string[] {
  const graded = contracts.filter((c) => c.verdict && c.verdict.verdict !== "insufficient_data");
  if (graded.length < 2) return [];
  const counts = new Map<string, number>();
  for (const c of graded) for (const f of new Set(c.verdict!.flags)) counts.set(f, (counts.get(f) ?? 0) + 1);
  return [...counts.entries()].filter(([, n]) => n === graded.length).map(([f]) => f);
}

/** Human sentence for each hoisted chain-wide flag. */
export function chainWideFlagNotes(flags: string[]): string[] {
  return flags.map((f) => FLAG_CHAIN_WIDE_NOTES[f] ?? `${FLAG_LABELS[f] ?? f.toUpperCase()} applies to every strike on this expiry.`);
}

/**
 * Ordered flag labels for the badge strip on a row, minus any flag hoisted to chain level.
 */
export function flagLabels(verdict: ContractVerdict | null | undefined, hoisted: readonly string[] = []): string[] {
  if (!verdict) return [];
  return verdict.flags.filter((f) => !hoisted.includes(f)).map((f) => FLAG_LABELS[f] ?? f.toUpperCase());
}

/**
 * True when Greek provenance varies across the chain, so the per-row MODEL badge carries
 * information. When every contract has the same provenance the header badge already says so.
 */
export function greekProvenanceIsMixed(contracts: ChainContractRow[]): boolean {
  const seen = new Set(contracts.map((c) => c.greeks_source));
  return seen.size > 1;
}

/**
 * Does a loaded analysis actually match the expiry the session asked for?
 * Guards the case where the trader changes the dashboard expiry mid-session.
 */
export function expiryMatches(analysis: Pick<ChainAnalysis, "expiry"> | null | undefined, sessionExpiry: string): boolean {
  if (!analysis?.expiry || !sessionExpiry) return false;
  return analysis.expiry === sessionExpiry;
}

/** True when the payload is a real chain worth rendering a table for. */
export function hasRenderableChain(analysis: ChainAnalysis | null | undefined): boolean {
  return Boolean(analysis && Array.isArray(analysis.contracts) && analysis.contracts.length > 0);
}
