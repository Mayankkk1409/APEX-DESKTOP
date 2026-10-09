/** User-facing strategy label — backend may still emit legacy Gamma Trampoline names. */
export function normalizeStrategyName(name: string | null | undefined): string {
  if (!name?.trim()) return "—";
  return name
    .replace(/Gamma\s*Trampoline™?/gi, "APEX Strategy")
    .replace(/GAMMA\s*TRAMPOLINE™?/gi, "APEX Strategy")
    .trim();
}

export const INSUFFICIENT_CONVICTION_SCORE = 50;

export function isInsufficientConviction(score: number | null | undefined): boolean {
  return score == null || !Number.isFinite(score) || score < INSUFFICIENT_CONVICTION_SCORE;
}
