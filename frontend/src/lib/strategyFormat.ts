export function formatBreakevens(breakevens: (number | null | undefined)[] | undefined): string {
  if (!breakevens?.length) return "—";
  const clean = breakevens.filter((b): b is number => b != null && Number.isFinite(b));
  if (!clean.length) return "—";
  return clean.map((b) => b.toFixed(2)).join(" · ");
}

export function formatStrategyPremium(
  value: number | null | undefined,
  netType: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const label = netType === "credit" ? "credit" : "debit";
  return `$${value.toFixed(2)} ${label}`;
}
