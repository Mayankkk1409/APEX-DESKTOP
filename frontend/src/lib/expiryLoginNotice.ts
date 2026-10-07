import { parseOccSymbol } from "./optionSymbolParse";
import { normalizeStrategyName } from "./strategyDisplay";
import { expiryNoticeStorageKey, sortExpiryItems, type ExpiryNoticeItem } from "./expiryNotice";

export const EXPIRY_LOGIN_WINDOW_DAYS = 7;

/** Written only after ExpiryLoginCertificate is committed. The watch-notice key is not this. */
export const EXPIRY_LOGIN_PAINTED_PREFIX = "apex_expiry_login_painted:";

export function expiryLoginPaintedKey(userId: string): string {
  return `${EXPIRY_LOGIN_PAINTED_PREFIX}${userId}`;
}

export type ExpiryLoginDayStore = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

export type ExpiryLoginCheck = "show" | "skip" | "cancelled";

export function readExpiryLoginDays(
  store: ExpiryLoginDayStore,
  userId: string,
): { paintedMarketDay: string | null; legacyNoticeDay: string | null } {
  return {
    paintedMarketDay: store.getItem(expiryLoginPaintedKey(userId)),
    legacyNoticeDay: store.getItem(expiryNoticeStorageKey(userId)),
  };
}

/**
 * Password or OTP verify shows the certificate whenever an open option is inside
 * the window. The painted-day key does not suppress that next login.
 * A page refresh or cookie restore passes credentialLogin false and stays quiet.
 */
export function shouldShowExpiryLoginCertificate(input: {
  rowCount: number;
  marketDay: string;
  paintedMarketDay: string | null;
  legacyNoticeDay: string | null;
  credentialLogin: boolean;
}): boolean {
  if (!input.credentialLogin) return false;
  if (input.rowCount <= 0) return false;
  void input.marketDay;
  void input.paintedMarketDay;
  void input.legacyNoticeDay;
  return true;
}

/** Navigate only when there is nothing to show. A cancelled check must not leave the page. */
export function expiryLoginShouldNavigate(result: ExpiryLoginCheck): boolean {
  return result === "skip";
}

/** Call from the effect that runs after the certificate is on screen, not before it renders. */
export function markExpiryLoginCertificatePainted(store: ExpiryLoginDayStore, userId: string, marketDay: string): void {
  store.setItem(expiryLoginPaintedKey(userId), marketDay);
  store.setItem(expiryNoticeStorageKey(userId), marketDay);
}

export const EXPIRY_LOGIN_AUTO_CLOSE =
  "These positions will be closed automatically at 16:00 America/New_York on the expiry day if still open.";

/** Read-only brokerage books are listed but never traded by the desk. */
export const EXPIRY_LOGIN_BROKER_SETTLES =
  "Read-only brokerage positions are settled by your broker. APEX does not place orders for them.";

export type ExpiryLoginRow = {
  key: string;
  positionId: string | null;
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
        positionId: item.position_id ?? null,
        symbol: parsed?.root ?? item.symbol,
        strategy: knownStrategy(item.strategy),
        expiryLabel: formatExpiryLoginDate(item.expiry),
        strikeLabel: formatStrike(strike),
        right,
        direction: asDirection(item.direction),
      };
    });
}

/** A paper ledger row is the only kind the 16:00 America/New_York job can close. */
export function isDeskManaged(row: ExpiryLoginRow, isPaper: boolean): boolean {
  return isPaper && row.positionId != null;
}

/**
 * Sentences under the title. The auto-close promise is only made for rows the
 * desk actually closes, so a read-only brokerage book is never told that APEX
 * will trade it.
 */
export function expiryLoginNotes(rows: readonly ExpiryLoginRow[], isPaper: boolean): string[] {
  const notes: string[] = [];
  if (rows.some((row) => isDeskManaged(row, isPaper))) notes.push(EXPIRY_LOGIN_AUTO_CLOSE);
  if (rows.some((row) => !isDeskManaged(row, isPaper))) notes.push(EXPIRY_LOGIN_BROKER_SETTLES);
  return notes;
}

export function formatRightLabel(right: "call" | "put" | null): string {
  if (right === "call") return "Call";
  if (right === "put") return "Put";
  return "—";
}

export function formatDirectionLabel(direction: "long" | "short" | null): string {
  if (direction === "long") return "Long";
  if (direction === "short") return "Short";
  return "—";
}
