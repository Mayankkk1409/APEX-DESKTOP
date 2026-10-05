export const EXPIRY_AUTO_CLOSE_NOTICE =
  "Positions still open at the cutoff on their expiry day will be closed automatically.";

export const EXPIRY_NOTICE_STORAGE_PREFIX = "apex_expiry_notice_day:";

export type ExpiryNoticeItem = {
  position_id: string | null;
  symbol: string;
  strategy: string;
  expiry: string;
  days_left: number;
  can_close: boolean;
};

export type ExpiryWatchResponse = {
  market_day: string;
  notice: string;
  is_paper: boolean;
  items: ExpiryNoticeItem[];
};

export function expiryNoticeStorageKey(userId: string): string {
  return `${EXPIRY_NOTICE_STORAGE_PREFIX}${userId}`;
}

/** Login always shows the notice when trades are inside the window. An existing session shows it once per New York market day. */
export function shouldShowExpiryNotice(input: {
  itemCount: number;
  justLoggedIn: boolean;
  marketDay: string;
  lastShownMarketDay: string | null;
}): boolean {
  if (input.itemCount <= 0) return false;
  if (input.justLoggedIn) return true;
  return input.lastShownMarketDay !== input.marketDay;
}

export function sortExpiryItems<T extends { days_left: number; symbol: string }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => a.days_left - b.days_left || a.symbol.localeCompare(b.symbol));
}

export function formatDaysLeft(days: number): string {
  if (days === 1) return "1 day left";
  return `${days} days left`;
}
