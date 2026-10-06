import { describe, expect, it } from "vitest";
import { expiryLoginRows, withinExpiryLoginWindow } from "./expiryLoginNotice";
import type { ExpiryNoticeItem } from "./expiryNotice";

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
});
