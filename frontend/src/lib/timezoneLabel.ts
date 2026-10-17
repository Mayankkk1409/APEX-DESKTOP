/** Readable label for a stored timezone id. The id itself is not rewritten. */
export function timezoneDisplayLabel(zone: string): string {
  if (zone === "America/New_York") return "New York";
  return zone;
}
