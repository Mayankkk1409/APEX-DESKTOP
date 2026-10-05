import { describe, expect, it } from "vitest";
import { buildEquitySeries } from "./pnlSeries";

describe("buildEquitySeries", () => {
  it("returns no bars when there is no history", () => {
    expect(buildEquitySeries([])).toEqual([]);
    expect(buildEquitySeries([], 25000)).toEqual([]);
  });

  it("skips points with invalid time or equity", () => {
    expect(
      buildEquitySeries([
        { t: "not-a-date", portfolio_value: 100 },
        { t: "2026-08-01T00:00:00Z", portfolio_value: Number.NaN },
      ]),
    ).toEqual([]);
  });

  it("keeps ledger equity and pins the last bar to the headline account equity", () => {
    const series = buildEquitySeries(
      [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 30000, balance: 5000 },
        { t: "2026-08-27T12:00:00Z", portfolio_value: 31000, balance: 4000 },
      ],
      33000,
    );
    expect(series).toHaveLength(2);
    expect(series[0].value).toBe(30000);
    expect(series[1].value).toBe(33000);
    expect(typeof series[0].time).toBe("number");
    expect(Number(series[1].time)).toBeGreaterThan(Number(series[0].time));
  });

  it("does not insert bars between observations", () => {
    const series = buildEquitySeries([
      { t: "2026-08-01T00:00:00Z", portfolio_value: 10000 },
      { t: "2026-08-10T00:00:00Z", portfolio_value: 11000 },
    ]);
    expect(series).toHaveLength(2);
    expect(series[0].value).toBe(10000);
    expect(series[1].value).toBe(11000);
  });

  it("does not add a synthetic earlier bar for a single point", () => {
    const series = buildEquitySeries([{ t: "2026-08-01T00:00:00Z", portfolio_value: 10000 }]);
    expect(series).toHaveLength(1);
    expect(series[0].value).toBe(10000);
  });

  it("collapses timestamps in the same second and keeps the later equity", () => {
    const series = buildEquitySeries([
      { t: "2026-08-01T00:00:00.100Z", portfolio_value: 10000 },
      { t: "2026-08-01T00:00:00.900Z", portfolio_value: 10100 },
    ]);
    expect(series).toHaveLength(1);
    expect(series[0].value).toBe(10100);
  });
});
