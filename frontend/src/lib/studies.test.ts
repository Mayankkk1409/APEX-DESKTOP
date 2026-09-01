import { describe, expect, it } from "vitest";
import {
  APEX_PIVOT_CONFIG,
  aggregatePivotPeriods,
  atrSeries,
  autoPivotResolution,
  bollingerSeries,
  computePivotSets,
  computeStudies,
  emaSeries,
  lastValue,
  macdSeries,
  pivotLabel,
  pivotRows,
  resolvePivotResolution,
  rmaSeries,
  rsiSeries,
  smaSeries,
  supertrendSeries,
  traditionalPivots,
} from "./studies";
import type { OhlcBar } from "./ta";

function bar(t: string, o: number, h: number, l: number, c: number, v = 1000): OhlcBar {
  return { t, o, h, l, c, v };
}

/** Deterministic wave so the fixtures are stable across runs. */
function wave(n: number, start = 100): OhlcBar[] {
  const out: OhlcBar[] = [];
  let px = start;
  for (let i = 0; i < n; i++) {
    const drift = Math.sin(i / 7) * 2 + i * 0.08;
    const c = start + drift;
    const o = px;
    out.push(
      bar(
        new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
        o,
        Math.max(o, c) + 0.9,
        Math.min(o, c) - 0.9,
        c,
        1_000_000 + i * 137,
      ),
    );
    px = c;
  }
  return out;
}

describe("SMA / EMA follow Pine semantics", () => {
  it("SMA is null before the window is full and matches the arithmetic mean", () => {
    const v = [1, 2, 3, 4, 5, 6];
    const out = smaSeries(v, 3);
    expect(out.slice(0, 2)).toEqual([null, null]);
    expect(out[2]).toBeCloseTo(2, 10);
    expect(out[5]).toBeCloseTo(5, 10);
  });

  it("EMA seeds with the SMA of the first `period` closes", () => {
    const v = [10, 11, 12, 13, 14];
    const out = emaSeries(v, 3);
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(out[2]).toBeCloseTo(11, 10); // sma(10,11,12)
    expect(out[3]).toBeCloseTo(13 * 0.5 + 11 * 0.5, 10);
    expect(out[4]).toBeCloseTo(14 * 0.5 + 12 * 0.5, 10);
  });

  it("EMA 200 on a short history stays undefined instead of drawing a garbage line", () => {
    const short = wave(60);
    const s = computeStudies(short);
    expect(lastValue(s.ema[200])).toBeNull();
    expect(s.ema[200].every((x) => x == null)).toBe(true);
    expect(lastValue(s.ema[50])).not.toBeNull();
  });

  it("Wilder RMA seeds with an SMA then decays by 1/period", () => {
    const v = [1, 2, 3, 4, 5];
    const out = rmaSeries(v, 3);
    expect(out[2]).toBeCloseTo(2, 10);
    expect(out[3]).toBeCloseTo((2 * 2 + 4) / 3, 10);
  });
});

describe("RSI 14", () => {
  it("returns 100 on an unbroken advance and null during warm-up", () => {
    const closes = Array.from({ length: 30 }, (_, i) => 100 + i);
    const out = rsiSeries(closes, 14);
    expect(out.slice(0, 14).every((x) => x == null)).toBe(true);
    expect(out[14]).toBeCloseTo(100, 6);
    expect(out[29]).toBeCloseTo(100, 6);
  });

  it("returns 0 on an unbroken decline", () => {
    const closes = Array.from({ length: 30 }, (_, i) => 100 - i);
    const out = rsiSeries(closes, 14);
    expect(out[20]).toBeCloseTo(0, 6);
  });

  it("matches a hand-computed Wilder RSI on a known fixture", () => {
    // Classic Wilder worked example (Technical Analysis of the Futures Markets).
    const closes = [
      44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.0,
      46.03, 46.41, 46.22, 45.64,
    ];
    const out = rsiSeries(closes, 14);
    // Published table: 70.53, 66.32, …, 57.97 (tables are rounded per step).
    expect(Math.abs((out[14] as number) - 70.53)).toBeLessThan(0.15);
    expect(Math.abs((out[15] as number) - 66.32)).toBeLessThan(0.15);
    expect(Math.abs((out[19] as number) - 57.97)).toBeLessThan(0.15);
  });

  it("stays inside 0..100 for a noisy series", () => {
    const s = computeStudies(wave(300));
    for (const v of s.rsi) if (v != null) expect(v).toBeGreaterThanOrEqual(0), expect(v).toBeLessThanOrEqual(100);
  });
});

describe("MACD 12/26/9", () => {
  it("line is null until the slow EMA exists and signal lags it by 8 bars", () => {
    const closes = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 5) * 3);
    const m = macdSeries(closes, 12, 26, 9);
    expect(m.line.slice(0, 25).every((x) => x == null)).toBe(true);
    expect(m.line[25]).not.toBeNull();
    expect(m.signal.slice(0, 33).every((x) => x == null)).toBe(true);
    expect(m.signal[33]).not.toBeNull();
  });

  it("line equals EMA12 − EMA26 and histogram equals line − signal", () => {
    const closes = Array.from({ length: 80 }, (_, i) => 100 + i * 0.4);
    const m = macdSeries(closes, 12, 26, 9);
    const f = emaSeries(closes, 12);
    const s = emaSeries(closes, 26);
    const i = 70;
    expect(m.line[i] as number).toBeCloseTo((f[i] as number) - (s[i] as number), 10);
    expect(m.histogram[i] as number).toBeCloseTo((m.line[i] as number) - (m.signal[i] as number), 10);
  });
});

describe("Bollinger 20/2", () => {
  it("bands are basis ± 2 population standard deviations", () => {
    const closes = Array.from({ length: 40 }, (_, i) => 100 + (i % 4));
    const bb = bollingerSeries(closes, 20, 2);
    const i = 39;
    const win = closes.slice(i - 19, i + 1);
    const mean = win.reduce((a, b) => a + b, 0) / 20;
    const sd = Math.sqrt(win.reduce((a, x) => a + (x - mean) ** 2, 0) / 20);
    expect(bb.basis[i] as number).toBeCloseTo(mean, 10);
    expect(bb.upper[i] as number).toBeCloseTo(mean + 2 * sd, 10);
    expect(bb.lower[i] as number).toBeCloseTo(mean - 2 * sd, 10);
    expect(bb.basis.slice(0, 19).every((x) => x == null)).toBe(true);
  });

  it("collapses to zero width on a flat series", () => {
    const bb = bollingerSeries(new Array(30).fill(50), 20, 2);
    expect(bb.upper[29] as number).toBeCloseTo(50, 10);
    expect(bb.width[29] as number).toBeCloseTo(0, 10);
  });
});

describe("ATR + SuperTrend ATR10 factor 3", () => {
  it("ATR of a constant-range series equals that range", () => {
    const bars = Array.from({ length: 30 }, (_, i) => bar(`2026-01-${String(i + 1).padStart(2, "0")}`, 100, 102, 98, 100));
    const a = atrSeries(bars, 10);
    expect(a.slice(0, 9).every((x) => x == null)).toBe(true);
    expect(a[20] as number).toBeCloseTo(4, 6);
  });

  it("tracks below price in an uptrend and flips above it in a downtrend", () => {
    const up = Array.from({ length: 60 }, (_, i) =>
      bar(`u${i}`, 100 + i, 101 + i, 99 + i, 100.5 + i),
    );
    const st = supertrendSeries(up, 10, 3);
    const last = st.value.length - 1;
    expect(st.direction[last]).toBe(1);
    expect(st.value[last] as number).toBeLessThan(up[last].c);

    const down = Array.from({ length: 60 }, (_, i) => bar(`d${i}`, 200 - i, 201 - i, 199 - i, 199.5 - i));
    const stD = supertrendSeries(down, 10, 3);
    const lastD = stD.value.length - 1;
    expect(stD.direction[lastD]).toBe(-1);
    expect(stD.value[lastD] as number).toBeGreaterThan(down[lastD].c);
  });
});

describe("Pivot Points Standard — Traditional", () => {
  it("matches the published Traditional formula", () => {
    const h = 110;
    const l = 90;
    const c = 105;
    const p = (h + l + c) / 3;
    const lv = traditionalPivots(h, l, c);
    expect(lv.p).toBeCloseTo(p, 10);
    expect(lv.r1).toBeCloseTo(2 * p - l, 10);
    expect(lv.s1).toBeCloseTo(2 * p - h, 10);
    expect(lv.r2).toBeCloseTo(p + (h - l), 10);
    expect(lv.s2).toBeCloseTo(p - (h - l), 10);
    expect(lv.r3).toBeCloseTo(2 * p + (h - 2 * l), 10);
    expect(lv.s3).toBeCloseTo(2 * p - (2 * h - l), 10);
    expect(lv.r4).toBeCloseTo(3 * p + (h - 3 * l), 10);
    expect(lv.s4).toBeCloseTo(3 * p - (3 * h - l), 10);
    expect(lv.r5).toBeCloseTo(4 * p + (h - 4 * l), 10);
    expect(lv.s5).toBeCloseTo(4 * p - (4 * h - l), 10);
  });

  it("keeps the ladder monotonic around the central pivot", () => {
    const lv = traditionalPivots(110, 90, 105);
    expect(lv.r5).toBeGreaterThan(lv.r4);
    expect(lv.r4).toBeGreaterThan(lv.r3);
    expect(lv.r3).toBeGreaterThan(lv.r2);
    expect(lv.r2).toBeGreaterThan(lv.r1);
    expect(lv.r1).toBeGreaterThan(lv.p);
    expect(lv.p).toBeGreaterThan(lv.s1);
    expect(lv.s1).toBeGreaterThan(lv.s2);
    expect(lv.s5).toBeLessThan(lv.s4);
  });

  it("uses the exact configuration from the signed-off settings dialog", () => {
    expect(APEX_PIVOT_CONFIG).toEqual({
      type: "Traditional",
      pivotsTimeframe: "AUTO",
      numberOfPivotsBack: 1,
      useDailyBasedValues: true,
      showLabels: true,
      showPrices: true,
      labelsPosition: "Left",
      lineWidth: 1,
    });
  });

  it("renders labels with prices, R5 → S5, using TradingView's `P` for the centre", () => {
    const rows = pivotRows(traditionalPivots(110, 90, 105));
    expect(rows.map((r) => r.label)).toEqual(["R5", "R4", "R3", "R2", "R1", "P", "S1", "S2", "S3", "S4", "S5"]);
    expect(pivotLabel({ key: "p", label: "P", price: 101.67 })).toBe("P (101.67)");
    expect(pivotLabel({ key: "r1", label: "R1", price: 113.33 }, { ...APEX_PIVOT_CONFIG, showPrices: false })).toBe("R1");
  });

  it("resolves Auto the way TradingView does", () => {
    expect(autoPivotResolution("1m")).toBe("D");
    expect(autoPivotResolution("5m")).toBe("D");
    expect(autoPivotResolution("15m")).toBe("D");
    expect(autoPivotResolution("30m")).toBe("W");
    expect(autoPivotResolution("1H")).toBe("W");
    expect(autoPivotResolution("4H")).toBe("W");
    expect(autoPivotResolution("1D")).toBe("M");
    expect(autoPivotResolution("1W")).toBe("12M");
    expect(resolvePivotResolution("1D", APEX_PIVOT_CONFIG)).toBe("M");
    expect(resolvePivotResolution("1D", { ...APEX_PIVOT_CONFIG, pivotsTimeframe: "D" })).toBe("D");
  });

  it("aggregates daily bars into monthly pivot periods", () => {
    const bars = [
      bar("2026-01-05T00:00:00Z", 100, 105, 95, 102),
      bar("2026-01-20T00:00:00Z", 102, 112, 99, 108),
      bar("2026-02-03T00:00:00Z", 108, 115, 104, 110),
    ];
    const periods = aggregatePivotPeriods(bars, "M");
    expect(periods).toHaveLength(2);
    expect(periods[0].high).toBe(112);
    expect(periods[0].low).toBe(95);
    expect(periods[0].close).toBe(108);
  });

  it("computes one level set from the last completed daily-based period", () => {
    const bars = [
      bar("2026-01-05T00:00:00Z", 100, 105, 95, 102),
      bar("2026-01-20T00:00:00Z", 102, 112, 99, 108),
      bar("2026-02-03T00:00:00Z", 108, 115, 104, 110),
    ];
    const sets = computePivotSets(bars, "1D", APEX_PIVOT_CONFIG);
    expect(sets).toHaveLength(APEX_PIVOT_CONFIG.numberOfPivotsBack);
    expect(sets[0].resolution).toBe("M");
    expect(sets[0].levels).toEqual(traditionalPivots(112, 95, 108));
    expect(sets[0].activeFrom).toBe(Date.parse("2026-02-03T00:00:00Z"));
  });

  it("uses daily H/L/C even when the chart is intraday", () => {
    const daily = [
      bar("2026-03-02T00:00:00Z", 100, 110, 90, 105),
      bar("2026-03-03T00:00:00Z", 105, 108, 101, 103),
    ];
    const sets = computePivotSets(daily, "5m", APEX_PIVOT_CONFIG);
    expect(sets[0].resolution).toBe("D");
    expect(sets[0].levels).toEqual(traditionalPivots(110, 90, 105));
  });

  it("returns no levels when there is not a completed period yet", () => {
    expect(computePivotSets([bar("2026-03-02T00:00:00Z", 100, 110, 90, 105)], "1D")).toEqual([]);
    expect(computePivotSets([], "1D")).toEqual([]);
  });
});

describe("computeStudies bundle", () => {
  it("produces every documented study aligned to the bar array", () => {
    const bars = wave(320);
    const s = computeStudies(bars);
    for (const len of [9, 21, 50, 100, 200] as const) {
      expect(s.ema[len]).toHaveLength(bars.length);
      expect(lastValue(s.ema[len])).not.toBeNull();
    }
    expect(s.macd.line).toHaveLength(bars.length);
    expect(lastValue(s.macd.histogram)).not.toBeNull();
    expect(lastValue(s.rsi)).not.toBeNull();
    expect(lastValue(s.bb.upper)).not.toBeNull();
    expect(lastValue(s.supertrend.value)).not.toBeNull();
    expect(lastValue(s.sma200)).not.toBeNull();
  });

  it("survives an empty series without throwing", () => {
    const s = computeStudies([]);
    expect(s.ema[9]).toEqual([]);
    expect(lastValue(s.rsi)).toBeNull();
  });
});
