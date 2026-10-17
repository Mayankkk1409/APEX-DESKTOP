import { describe, expect, it } from "vitest";
import { PNL_LINE_DOWN, PNL_LINE_UP, buildEquitySeries, buildProfitSeries, colorProfitLine } from "./pnlSeries";

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

  it("updates the last bar when the headline is the same account, and leaves a different scale alone", () => {
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

    const cliff = buildEquitySeries(
      [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 100000 },
        { t: "2026-10-08T00:00:00Z", portfolio_value: 156000 },
      ],
      3124098.5,
    );
    expect(cliff).toHaveLength(3);
    expect(cliff[0].value).toBe(100000);
    expect(cliff[1].value).toBe(156000);
    expect(cliff[2].value).toBe(3124098.5);
    expect(Number(cliff[2].time)).toBeGreaterThan(Number(cliff[1].time));
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

describe("buildProfitSeries", () => {
  it("pins the latest P&L point to Overall P&L", () => {
    const series = buildProfitSeries(
      [
        { t: "2026-08-01T00:00:00Z", portfolio_value: 100000, cumulative_pl: 0 },
        { t: "2026-08-20T00:00:00Z", portfolio_value: 100100, cumulative_pl: 40 },
      ],
      100,
    );
    expect(series[0].value).toBe(0);
    expect(series[1].value).toBe(100);
  });
});

describe("colorProfitLine", () => {
  const at = (iso: string) => Math.floor(Date.parse(iso) / 1000);

  it("keeps a profit stretch green and a loss stretch red", () => {
    const colored = colorProfitLine([
      { time: at("2026-08-01T00:00:00Z") as never, value: 40 },
      { time: at("2026-08-02T00:00:00Z") as never, value: 10 },
      { time: at("2026-08-03T00:00:00Z") as never, value: -20 },
      { time: at("2026-08-04T00:00:00Z") as never, value: -5 },
      { time: at("2026-08-05T00:00:00Z") as never, value: 15 },
    ]);
    const values = colored.map((point) => point.value);
    expect(values).toEqual([40, 10, 0, -20, -5, 0, 15]);
    expect(colored.map((point) => point.color)).toEqual([
      PNL_LINE_UP,
      PNL_LINE_UP,
      PNL_LINE_DOWN,
      PNL_LINE_DOWN,
      PNL_LINE_DOWN,
      PNL_LINE_UP,
      PNL_LINE_UP,
    ]);
    const down = colored.find((point) => point.value === -20);
    const back = colored.filter((point) => point.value === 0);
    expect(down).toBeTruthy();
    expect(Number(back[0].time)).toBeGreaterThan(at("2026-08-02T00:00:00Z"));
    expect(Number(back[0].time)).toBeLessThan(at("2026-08-03T00:00:00Z"));
    expect(Number(back[1].time)).toBeGreaterThan(at("2026-08-04T00:00:00Z"));
    expect(Number(back[1].time)).toBeLessThan(at("2026-08-05T00:00:00Z"));
  });

  it("does not add a point when the series already touches zero", () => {
    const colored = colorProfitLine([
      { time: 1_700_000_000 as never, value: 5 },
      { time: 1_700_086_400 as never, value: 0 },
      { time: 1_700_172_800 as never, value: -5 },
    ]);
    expect(colored.map((point) => point.value)).toEqual([5, 0, -5]);
    expect(colored.map((point) => point.color)).toEqual([PNL_LINE_UP, PNL_LINE_DOWN, PNL_LINE_DOWN]);
  });
});
