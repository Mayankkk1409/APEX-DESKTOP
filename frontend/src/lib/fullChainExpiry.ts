/** A listed expiry with fewer calls than this cannot build a normal spread. */
export const FULL_CHAIN_CALLS = 8;

export type ListedExpiration = {
  date: string;
  listed?: number;
};

export function expiryHoldKey(symbol: string): string {
  return `apex-expiry-hold:${symbol.toUpperCase()}`;
}

export function readExpiryHold(symbol: string): string | null {
  try {
    return sessionStorage.getItem(expiryHoldKey(symbol));
  } catch {
    return null;
  }
}

export function writeExpiryHold(symbol: string, date: string): void {
  try {
    sessionStorage.setItem(expiryHoldKey(symbol), date);
  } catch {
    /* private mode */
  }
}

/**
 * The expiry the desk should scan.
 * A saved stub (a handful of calls) moves to the nearest full listing.
 * A date the user just picked is left alone, including a stub.
 */
export function preferredFullExpiry(
  list: ListedExpiration[],
  current: string,
  held: string | null,
): string | null {
  if (!list.length) return null;
  if (held && held === current && list.some((row) => row.date === current)) return null;
  const full = list.find((row) => (row.listed ?? 0) >= FULL_CHAIN_CALLS);
  const row = list.find((item) => item.date === current);
  if (!current || !row) return (full ?? list[0]).date;
  const listed = row.listed ?? 0;
  if (listed >= FULL_CHAIN_CALLS) return null;
  if (listed > 0 && full && full.date !== current) return full.date;
  return null;
}
