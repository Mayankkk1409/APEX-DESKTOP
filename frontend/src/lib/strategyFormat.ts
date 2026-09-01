import type { BreakevenRange, BreakevenValue } from "../types";

function isBreakevenRange(value: BreakevenValue): value is BreakevenRange {
  return (
    typeof value === "object" &&
    value != null &&
    value.type === "range" &&
    Number.isFinite(value.lower) &&
    Number.isFinite(value.upper)
  );
}

function formatBreakevenValue(value: BreakevenValue): string {
  if (isBreakevenRange(value)) {
    const lo = Math.min(value.lower, value.upper);
    const hi = Math.max(value.lower, value.upper);
    return `${lo.toFixed(2)} – ${hi.toFixed(2)}`;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(2);
  }
  return "—";
}

export function formatBreakevens(breakevens: (BreakevenValue | null | undefined)[] | undefined): string {
  if (!breakevens?.length) return "—";
  const clean = breakevens.filter((b): b is BreakevenValue => b != null);
  if (!clean.length) return "—";
  return clean.map(formatBreakevenValue).join(" · ");
}

export function breakevenIvAssumptionNote(
  breakevens: (BreakevenValue | null | undefined)[] | undefined,
  metrics?: {
    breakeven_iv_assumption?: boolean;
    breakeven_assumption_note?: string;
    notes?: string;
  } | null,
): string | null {
  if (metrics?.breakeven_assumption_note?.trim()) {
    return metrics.breakeven_assumption_note.trim();
  }
  if (metrics?.breakeven_iv_assumption) {
    return "Breakeven range assumes current implied volatility through front expiration.";
  }
  const rangeWithIv = breakevens?.find(
    (b): b is BreakevenRange => b != null && isBreakevenRange(b) && Boolean(b.iv_assumption),
  );
  if (rangeWithIv) {
    return "Breakeven range assumes current implied volatility through front expiration.";
  }
  return null;
}

export function formatStrategyPremium(
  value: number | null | undefined,
  netType: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const label = netType === "credit" ? "credit" : "debit";
  return `$${value.toFixed(2)} ${label}`;
}
