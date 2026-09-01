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

  it("anchors 1M window with a point before the cutoff", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    const filtered = filterPnlPoints(points, "1M", now);
    expect(filtered[0].t).toBe("2026-03-01T00:00:00Z");
    expect(filtered[filtered.length - 1].t).toBe("2026-08-01T00:00:00Z");
    expect(filtered.length).toBe(2);
  });

  it("computes timeframe start dates", () => {
    const now = new Date("2026-08-28T12:00:00Z");
    expect(timeframeStart("YTD", now)?.toISOString()).toBe("2026-01-01T00:00:00.000Z");
    expect(timeframeStart("MAX", now)).toBeNull();
  });
});
