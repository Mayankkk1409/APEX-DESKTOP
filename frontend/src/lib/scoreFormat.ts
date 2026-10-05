/**
 * Shared composite display. One rounding path, always one decimal.
 * 59 → "59.0". 62.9 → "62.9". Missing or non-finite → em dash.
 */
export function formatCompositeDecimal(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "—";
  return score.toFixed(1);
}

/** Certificate and strategy line — same decimal, with the / 100 scale. */
export function formatCompositeScore(score: number | null | undefined): string {
  const decimal = formatCompositeDecimal(score);
  if (decimal === "—") return decimal;
  return `${decimal} / 100`;
}
