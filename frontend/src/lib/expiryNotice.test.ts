import { describe, expect, it } from "vitest";
import { shouldShowExpiryNotice, sortExpiryItems } from "./expiryNotice";

describe("expiry notice", () => {
  it("no positions means no modal", () => {
    expect(
      shouldShowExpiryNotice({
        itemCount: 0,
        justLoggedIn: true,
        marketDay: "2026-10-02",
        lastShownMarketDay: null,
      }),
    ).toBe(false);
  });

  it("shows on login when trades expire inside the window", () => {
    expect(
      shouldShowExpiryNotice({
        itemCount: 2,
        justLoggedIn: true,
        marketDay: "2026-10-02",
        lastShownMarketDay: "2026-10-02",
      }),
    ).toBe(true);
  });

  it("shows an existing session once per market day", () => {
    expect(
      shouldShowExpiryNotice({
        itemCount: 1,
        justLoggedIn: false,
        marketDay: "2026-10-02",
        lastShownMarketDay: "2026-10-02",
      }),
    ).toBe(false);
    expect(
      shouldShowExpiryNotice({
        itemCount: 1,
        justLoggedIn: false,
        marketDay: "2026-10-05",
        lastShownMarketDay: "2026-10-02",
      }),
    ).toBe(true);
  });

  it("sorts soonest expiry first", () => {
    const sorted = sortExpiryItems([
      { symbol: "BBB", days_left: 5 },
      { symbol: "AAA", days_left: 0 },
      { symbol: "CCC", days_left: 0 },
    ]);
    expect(sorted.map((row) => row.symbol)).toEqual(["AAA", "CCC", "BBB"]);
  });
});
