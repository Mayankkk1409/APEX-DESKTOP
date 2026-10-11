import { describe, expect, it } from "vitest";
import { filterPnlPoints, timeframeStart } from "./pnlTimeframe";

const points = [
  { t: "2026-01-01T00:00:00Z", portfolio_value: 10000 },
  { t: "2026-02-01T00:00:00Z", portfolio_value: 11000 },
  { t: "2026-03-01T00:00:00Z", portfolio_value: 12000 },
  { t: "2026-08-01T00:00:00Z", portfolio_value: 13000 },
];

describe("pnlTimeframe", () => {
  it("returns all points for MAX", () => {
    expect(filterPnlPoints(points, "MAX")).toEqual(points);
  });

  it("filters to YTD from a fixed now", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    const filtered = filterPnlPoints(points, "YTD", now);
    expect(filtered.map((p) => p.t)).toEqual([
      "2026-01-01T00:00:00Z",
      "2026-02-01T00:00:00Z",
      "2026-03-01T00:00:00Z",
      "2026-08-01T00:00:00Z",
    ]);
  });

  it("keeps only points inside the 1M window", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    const filtered = filterPnlPoints(points, "1M", now);
    expect(filtered.map((p) => p.t)).toEqual(["2026-08-01T00:00:00Z"]);
  });

  it("keeps a point inside the one-week window and drops older ones", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    const filtered = filterPnlPoints(
      [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 1 },
        { t: "2026-08-24T00:00:00Z", portfolio_value: 2 },
        { t: "2026-08-27T00:00:00Z", portfolio_value: 3 },
      ],
      "1W",
      now,
    );
    expect(filtered.map((p) => p.portfolio_value)).toEqual([2, 3]);
  });

  it("keeps the last two closes when 1D falls on the weekend after the last session", () => {
    const now = new Date("2026-10-11T05:30:00Z");
    const filtered = filterPnlPoints(
      [
        { t: "2026-10-08T20:00:00Z", portfolio_value: 10, cumulative_pl: 1 },
        { t: "2026-10-09T20:00:00Z", portfolio_value: 11, cumulative_pl: 2 },
      ],
      "1D",
      now,
    );
    expect(filtered.map((p) => p.portfolio_value)).toEqual([10, 11]);
  });

  it("does not draw a line from the first point to the last when the window is empty", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    const filtered = filterPnlPoints(
      [
        { t: "2025-01-01T00:00:00Z", portfolio_value: 1 },
        { t: "2026-08-01T00:00:00Z", portfolio_value: 2 },
      ],
      "1D",
      now,
    );
    expect(filtered).toEqual([]);
  });

  it("computes timeframe start dates", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    expect(timeframeStart("YTD", now)?.toISOString()).toBe("2026-01-01T00:00:00.000Z");
    expect(timeframeStart("MAX", now)).toBeNull();
  });
});
