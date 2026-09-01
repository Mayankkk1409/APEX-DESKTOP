/** Composite score for certificates and hero displays — e.g. "72.4 / 100". */
export function formatCompositeScore(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "—";
  return `${score.toFixed(1)} / 100`;
}
