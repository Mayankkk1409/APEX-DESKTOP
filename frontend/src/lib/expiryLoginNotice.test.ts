import { describe, expect, it } from "vitest";
import { expiryNoticeStorageKey, type ExpiryNoticeItem } from "./expiryNotice";
import {
  EXPIRY_LOGIN_AUTO_CLOSE,
  EXPIRY_LOGIN_BROKER_SETTLES,
  expiryLoginNotes,
  expiryLoginPaintedKey,
  expiryLoginRows,
  expiryLoginShouldNavigate,
  markExpiryLoginCertificatePainted,
  readExpiryLoginDays,
  shouldShowExpiryLoginCertificate,
  withinExpiryLoginWindow,
  type ExpiryLoginDayStore,
} from "./expiryLoginNotice";

const MARKET_DAY = "2026-10-02";

function item(over: Partial<ExpiryNoticeItem> & Pick<ExpiryNoticeItem, "symbol" | "expiry">): ExpiryNoticeItem {
  return {
    position_id: over.position_id ?? over.symbol,
    strategy: over.strategy ?? "Bull Call Spread",
    days_left: over.days_left ?? 0,
    can_close: over.can_close ?? true,
    ...over,
  };
}

describe("expiry login window", () => {
  it("includes a position expiring today and excludes one 8 days out", () => {
    expect(withinExpiryLoginWindow(MARKET_DAY, MARKET_DAY)).toBe(true);
    expect(withinExpiryLoginWindow(MARKET_DAY, "2026-10-09")).toBe(true);
    expect(withinExpiryLoginWindow(MARKET_DAY, "2026-10-10")).toBe(false);

    const rows = expiryLoginRows(
      [
        item({
          position_id: "today",
          symbol: "AAPL261002C00150000",
          strategy: "Bull Call Spread",
          expiry: "2026-10-02",
          days_left: 0,
          strike: 150,
          right: "call",
          direction: "long",
        }),
        item({
          position_id: "later",
          symbol: "MSFT261010P00400000",
          strategy: "Bear Put Spread",
          expiry: "2026-10-10",
          days_left: 8,
          strike: 400,
          right: "put",
          direction: "short",
        }),
      ],
      MARKET_DAY,
    );

    expect(rows.map((row) => row.key)).toEqual(["today"]);
    expect(rows[0]).toMatchObject({
      symbol: "AAPL",
      strategy: "Bull Call Spread",
      expiryLabel: "Oct 2, 2026",
      strikeLabel: "150",
      right: "call",
      direction: "long",
    });
  });

  it("formats a later day inside the window as Oct 9, 2026 and hides an unknown strategy", () => {
    const rows = expiryLoginRows(
      [
        item({
          position_id: "oct9",
          symbol: "AAPL261009C00150000",
          strategy: "—",
          expiry: "2026-10-09",
          days_left: 7,
          direction: "short",
        }),
      ],
      MARKET_DAY,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].expiryLabel).toBe("Oct 9, 2026");
    expect(rows[0].strategy).toBeNull();
    expect(rows[0].strikeLabel).toBe("150");
    expect(rows[0].right).toBe("call");
    expect(rows[0].direction).toBe("short");
  });

  it("holds the window across a month boundary", () => {
    expect(withinExpiryLoginWindow("2026-10-26", "2026-11-02")).toBe(true);
    expect(withinExpiryLoginWindow("2026-10-26", "2026-11-03")).toBe(false);
    expect(withinExpiryLoginWindow("2026-10-02", "2026-10-01")).toBe(false);
  });
});

describe("expiryLoginNotes", () => {
  const paperRow = {
    key: "pos-1",
    positionId: "pos-1",
    symbol: "AAPL",
    strategy: "Bull Call Spread",
    expiryLabel: "Oct 9, 2026",
    strikeLabel: "150",
    right: "call" as const,
    direction: "long" as const,
  };
  const brokerRow = { ...paperRow, key: "NVDA", positionId: null, symbol: "NVDA" };

  it("promises the 16:00 New York close only for paper ledger rows", () => {
    expect(expiryLoginNotes([paperRow], true)).toEqual([EXPIRY_LOGIN_AUTO_CLOSE]);
    expect(expiryLoginNotes([brokerRow], true)).toEqual([EXPIRY_LOGIN_BROKER_SETTLES]);
    expect(expiryLoginNotes([paperRow, brokerRow], true)).toEqual([
      EXPIRY_LOGIN_AUTO_CLOSE,
      EXPIRY_LOGIN_BROKER_SETTLES,
    ]);
    expect(expiryLoginNotes([paperRow], false)).toEqual([EXPIRY_LOGIN_BROKER_SETTLES]);
    expect(expiryLoginNotes([], true)).toEqual([]);
  });
});

function memoryStore(): ExpiryLoginDayStore {
  const data = new Map<string, string>();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
  };
}

describe("expiry login trigger", () => {
  const marketDay = "2026-10-06";
  const userId = "user-1";

  it("shows when the notice key was stored before the certificate painted", () => {
    const store = memoryStore();
    store.setItem(expiryNoticeStorageKey(userId), marketDay);
    const days = readExpiryLoginDays(store, userId);
    expect(days.paintedMarketDay).toBeNull();
    expect(
      shouldShowExpiryLoginCertificate({
        rowCount: 1,
        marketDay,
        paintedMarketDay: days.paintedMarketDay,
        legacyNoticeDay: days.legacyNoticeDay,
      }),
    ).toBe(true);
    expect(expiryLoginShouldNavigate("show")).toBe(false);
    expect(expiryLoginShouldNavigate("cancelled")).toBe(false);
  });

  it("stays quiet for the rest of the market day after the certificate paints", () => {
    const store = memoryStore();
    store.setItem(expiryNoticeStorageKey(userId), marketDay);
    markExpiryLoginCertificatePainted(store, userId, marketDay);
    const days = readExpiryLoginDays(store, userId);
    expect(days.paintedMarketDay).toBe(marketDay);
    expect(store.getItem(expiryLoginPaintedKey(userId))).toBe(marketDay);
    expect(store.getItem(expiryNoticeStorageKey(userId))).toBe(marketDay);
    expect(
      shouldShowExpiryLoginCertificate({
        rowCount: 1,
        marketDay,
        paintedMarketDay: days.paintedMarketDay,
        legacyNoticeDay: days.legacyNoticeDay,
      }),
    ).toBe(false);
    expect(expiryLoginShouldNavigate("skip")).toBe(true);
  });

  it("shows nothing when no open option is inside the window", () => {
    expect(
      shouldShowExpiryLoginCertificate({
        rowCount: 0,
        marketDay,
        paintedMarketDay: null,
        legacyNoticeDay: null,
      }),
    ).toBe(false);
    expect(expiryLoginShouldNavigate("skip")).toBe(true);
  });
});
