import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DailyPnlList, PositionDailyPnl } from "./DailyPnlList";
import { dayPlOrUnrealized, type DailyPnlDay } from "../lib/dailyPnl";

const days: DailyPnlDay[] = [
  { date: "2026-10-01", pnl: 12.5, status: "marked" },
  { date: "2026-10-02", pnl: -4, status: "marked" },
  { date: "2026-10-05", pnl: null, status: "unavailable" },
];

describe("PositionDailyPnl", () => {
  it("renders each daily value and labels a missing day unavailable", () => {
    const html = renderToStaticMarkup(<PositionDailyPnl symbol="AAPL" days={days} />);
    expect(html).toContain("AAPL daily P/L");
    expect(html).toContain('data-date="2026-10-01"');
    expect(html).toContain('data-date="2026-10-02"');
    expect(html).toContain('data-date="2026-10-05"');
    expect(html).toContain("+$12.5");
    expect(html).toContain("-$4");
    const missing = html.match(/data-date="2026-10-05"[\s\S]*?<\/li>/);
    expect(missing?.[0]).toContain("unavailable");
    expect(missing?.[0]).toContain('data-status="unavailable"');
    expect(missing?.[0]).not.toMatch(/\$/);
  });

  it("does not drop a day or replace a missing mark with zero", () => {
    const html = renderToStaticMarkup(<DailyPnlList days={[{ date: "2026-10-06", pnl: null, status: "unavailable" }]} />);
    expect(html).toContain('data-date="2026-10-06"');
    expect(html).toContain("unavailable");
    expect(html).not.toContain("$0");
    expect(html).not.toContain("+$0");
  });
});

describe("dayPlOrUnrealized", () => {
  it("uses the latest marked session", () => {
    expect(dayPlOrUnrealized(days.slice(0, 2), 999)).toBe(-4);
  });

  it("keeps unrealized P&L when the latest session has no price", () => {
    expect(dayPlOrUnrealized([{ date: "2026-10-06", pnl: null, status: "unavailable" }], 42)).toBe(42);
  });

  it("does not invent a number before the daily series has loaded", () => {
    expect(dayPlOrUnrealized(undefined, 42)).toBeNull();
  });
});
