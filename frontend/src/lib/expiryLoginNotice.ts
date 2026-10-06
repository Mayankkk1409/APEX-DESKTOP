import { parseOccSymbol } from "./optionSymbolParse";
import { normalizeStrategyName } from "./strategyDisplay";
import { sortExpiryItems, type ExpiryNoticeItem } from "./expiryNotice";

export const EXPIRY_LOGIN_WINDOW_DAYS = 7;

export const EXPIRY_LOGIN_AUTO_CLOSE =
  "These positions will be closed automatically at 16:00 America/New_York on the expiry day if still open.";

export type ExpiryLoginRow = {
  key: string;
  symbol: string;
  strategy: string | null;
  expiryLabel: string;
  strikeLabel: string;
  right: "call" | "put" | null;
  direction: "long" | "short" | null;
};

/** Calendar-day distance from a New York market day to an expiry date. */
export function calendarDaysUntil(marketDay: string, expiry: string): number | null {
  const today = marketDay.slice(0, 10);
  const exp = expiry.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(today) || !/^\d{4}-\d{2}-\d{2}$/.test(exp)) return null;
  const start = Date.parse(`${today}T00:00:00Z`);
  const end = Date.parse(`${exp}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.round((end - start) / 86_400_000);
}

export function withinExpiryLoginWindow(marketDay: string, expiry: string): boolean {
  const days = calendarDaysUntil(marketDay, expiry);
  return days != null && days >= 0 && days <= EXPIRY_LOGIN_WINDOW_DAYS;
}

export function formatExpiryLoginDate(expiry: string): string {
  const iso = expiry.slice(0, 10);
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return expiry;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatStrike(strike: number | null | undefined): string {
  if (strike == null || !Number.isFinite(strike)) return "—";
  if (Math.abs(strike - Math.round(strike)) < 1e-6) return String(Math.round(strike));
  return String(strike);
}

function knownStrategy(name: string | null | undefined): string | null {
  const label = normalizeStrategyName(name);
  if (!label || label === "—") return null;
  return label;
}

function asRight(value: string | null | undefined): "call" | "put" | null {
  if (value === "call" || value === "put") return value;
  return null;
}

function asDirection(value: string | null | undefined): "long" | "short" | null {
  if (value === "long" || value === "short") return value;
  return null;
}

/** One row per open option inside the 7-calendar-day window. An 8-day expiry is left out. */
export function expiryLoginRows(items: readonly ExpiryNoticeItem[], marketDay: string): ExpiryLoginRow[] {
  return sortExpiryItems(items)
    .filter((item) => withinExpiryLoginWindow(marketDay, item.expiry))
    .map((item) => {
      const parsed = parseOccSymbol(item.symbol);
      const right = asRight(item.right) ?? parsed?.side ?? null;
      const strike = item.strike ?? parsed?.strike ?? null;
      return {
        key: item.position_id ?? item.symbol,
        symbol: parsed?.root ?? item.symbol,
        strategy: knownStrategy(item.strategy),
        expiryLabel: formatExpiryLoginDate(item.expiry),
        strikeLabel: formatStrike(strike),
        right,
        direction: asDirection(item.direction),
      };
    });
}
