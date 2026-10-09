import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DailyPnlList, PositionDailyPnl } from "./DailyPnlList";
import { dayPlOrUnrealized, displaySessionDay, type DailyPnlDay } from "../lib/dailyPnl";

const days: DailyPnlDay[] = [
  { date: "2026-10-01", pnl: 12.5, status: "marked" },
  { date: "2026-10-02", pnl: -4, status: "marked" },
  { date: "2026-10-05", pnl: null, status: "unavailable" },
];

describe("PositionDailyPnl", () => {
  it("renders only the latest day that has a dollar P&L", () => {
    const html = renderToStaticMarkup(<PositionDailyPnl symbol="AAPL" days={days} />);
    expect(html).toContain("AAPL daily P/L");
    expect(html).toContain('data-date="2026-10-02"');
    expect(html).toContain("Oct 2");
    expect(html).toContain("-$4");
    expect(html).not.toContain('data-date="2026-10-01"');
    expect(html).not.toContain('data-date="2026-10-05"');
    expect(html).not.toContain("+$12.5");
    expect(html).not.toContain("unavailable");
    expect(html.match(/data-date=/g)).toHaveLength(1);
  });

  it("shows the latest date as unavailable when no day has a price", () => {
    const html = renderToStaticMarkup(
      <DailyPnlList
        days={[
          { date: "2026-10-05", pnl: null, status: "unavailable" },
          { date: "2026-10-06", pnl: null, status: "unavailable" },
        ]}
      />,
    );
    expect(html).toContain('data-date="2026-10-06"');
    expect(html).toContain("Oct 6");
    expect(html).not.toContain('data-date="2026-10-05"');
    expect(html).toContain("unavailable");
    expect(html).not.toContain("$0");
    expect(html).not.toContain("+$0");
    expect(html.match(/data-date=/g)).toHaveLength(1);
  });

  it("does not replace a single missing mark with zero", () => {
    const html = renderToStaticMarkup(<DailyPnlList days={[{ date: "2026-10-06", pnl: null, status: "unavailable" }]} />);
    expect(html).toContain('data-date="2026-10-06"');
    expect(html).toContain("unavailable");
    expect(html).not.toContain("$0");
    expect(html).not.toContain("+$0");
  });
});

describe("displaySessionDay", () => {
  it("picks the latest numeric day and otherwise the latest date", () => {
    expect(displaySessionDay(days)?.date).toBe("2026-10-02");
    expect(
      displaySessionDay([
        { date: "2026-10-05", pnl: null, status: "unavailable" },
        { date: "2026-10-06", pnl: null, status: "unavailable" },
      ])?.date,
    ).toBe("2026-10-06");
  });
});

describe("dayPlOrUnrealized", () => {
  it("uses the latest day that has a dollar P&L", () => {
    expect(dayPlOrUnrealized(days, 999)).toBe(-4);
  });

  it("keeps unrealized P&L when the latest session has no price", () => {
    expect(dayPlOrUnrealized([{ date: "2026-10-06", pnl: null, status: "unavailable" }], 42)).toBe(42);
  });

  it("does not invent a number before the daily series has loaded", () => {
    expect(dayPlOrUnrealized(undefined, 42)).toBeNull();
  });
});
