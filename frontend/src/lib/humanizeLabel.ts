/** Turn snake_case / camelCase enum tokens into readable labels (e.g. aggressive_bullish → Aggressive Bullish). */
export function humanizeLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || String(value).trim() === "") return "";
  return String(value)
    .replace(/_/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
