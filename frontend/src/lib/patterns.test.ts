import { describe, expect, it } from "vitest";
import { catalystIsDrawableOnChart, detectChartMarks, detectSrMarks, isEveningStar, isMorningStar, patternUsesBoxMark, type Catalyst } from "./patterns";
import type { OhlcBar } from "./ta";

function bar(t: string, o: number, h: number, l: number, c: number, v = 1_000_000): OhlcBar {
  return { t, o, h, l, c, v };
}

function downtrend(n: number, start = 120): OhlcBar[] {
  const out: OhlcBar[] = [];
  let px = start;
  for (let i = 0; i < n; i++) {
    const o = px;
    const c = px - 1.8;
    out.push(bar(`2026-01-${String(i + 1).padStart(2, "0")}`, o, o + 0.15, c - 0.2, c));
    px = c;
  }
  return out;
}

describe("isMorningStar", () => {
  it("accepts a textbook three-bar morning star", () => {
    const a = bar("t1", 100, 100.3, 93.8, 94.4);
    const m = bar("t2", 94.1, 94.6, 93.4, 93.8);
    const c = bar("t3", 94.6, 99.7, 94.3, 99.1);
    expect(isMorningStar(a, m, c, 2.4)).toBe(true);
  });

  it("rejects three consecutive down closes (not a morning star)", () => {
    const a = bar("t1", 100, 100.2, 97.0, 97.2);
    const m = bar("t2", 97.0, 97.3, 95.4, 95.6);
    const c = bar("t3", 95.5, 95.8, 93.8, 94.0);
    expect(isMorningStar(a, m, c, 2.0)).toBe(false);
  });

  it("rejects a third bar that fails to reclaim the first-bar midpoint", () => {
    const a = bar("t1", 100, 100.3, 93.8, 94.4);
    const m = bar("t2", 94.1, 94.6, 93.4, 93.8);
    const c = bar("t3", 94.0, 96.2, 93.9, 95.8);
    expect(isMorningStar(a, m, c, 2.4)).toBe(false);
  });
});

describe("isEveningStar", () => {
  it("accepts a textbook evening star and rejects a morning star fixture", () => {
    const a = bar("t1", 94.4, 100.3, 94.2, 100.0);
    const m = bar("t2", 100.4, 100.9, 99.8, 100.2);
    const c = bar("t3", 99.6, 99.8, 94.5, 94.9);
    expect(isEveningStar(a, m, c, 2.4)).toBe(true);
    expect(isMorningStar(a, m, c, 2.4)).toBe(false);
  });
});

describe("pattern mark classification", () => {
  const hs: Catalyst = {
    id: "hs",
    name: "Head & Shoulders",
    bias: "bearish",
    kind: "structure",
    barIndex: 0,
    barEnd: 20,
    price: 100,
    explain: "",
    confidence: 0.9,
  };
  const flag: Catalyst = {
    id: "flag",
    name: "Bull Flag",
    bias: "bullish",
    kind: "structure",
    barIndex: 0,
    barEnd: 18,
    price: 100,
    explain: "",
    confidence: 0.74,
  };
  const star: Catalyst = {
    id: "star",
    name: "Morning Star",
    bias: "bullish",
    kind: "candle",
    barIndex: 10,
    barEnd: 12,
    price: 95,
    explain: "",
    confidence: 0.93,
  };
  const sr: Catalyst = {
    id: "sr",
    name: "Support",
    bias: "bullish",
    kind: "level",
    barIndex: 0,
    price: 95,
    explain: "",
    confidence: 0.8,
  };

  it("uses boxes for large structures and circles for small candle prints", () => {
    expect(patternUsesBoxMark(hs)).toBe(true);
    expect(patternUsesBoxMark(flag)).toBe(true);
    expect(patternUsesBoxMark(star)).toBe(false);
  });

  it("draws structures and candle/momentum crosses but not S/R or SuperTrend", () => {
    expect(catalystIsDrawableOnChart(hs)).toBe(true);
    expect(catalystIsDrawableOnChart(star)).toBe(true);
    expect(catalystIsDrawableOnChart(sr)).toBe(false);
    expect(
      catalystIsDrawableOnChart({
        id: "st",
        name: "SuperTrend bullish flip",
        bias: "bullish",
        kind: "momentum",
        barIndex: 5,
        price: 100,
        explain: "",
        confidence: 0.9,
      }),
    ).toBe(false);
  });
});

describe("detectChartMarks", () => {
  it("detects a morning star only when those three candles are in the viewport", () => {
    const prefix = downtrend(16, 130);
    const star = [
      bar("2026-02-01", 100, 100.3, 93.8, 94.4),
      bar("2026-02-02", 94.1, 94.6, 93.4, 93.8),
      bar("2026-02-03", 94.6, 99.7, 94.3, 99.1, 2_400_000),
    ];
    const found = detectChartMarks([...prefix, ...star]).filter((m) => m.name === "Morning Star");
    expect(found).toHaveLength(1);
    expect(found[0].barIndex).toBe(prefix.length);
    expect(found[0].barEnd).toBe(prefix.length + 2);
    expect(found[0].kind).toBe("candle");
  });

  it("does not invent a morning star on a continued selloff", () => {
    const bars = downtrend(22, 140);
    const names = detectChartMarks(bars).map((m) => m.name);
    expect(names).not.toContain("Morning Star");
    expect(names).not.toContain("Three White Soldiers");
  });

  it("snapshot S/R drawings never include candlestick pattern boxes", () => {
    const prefix = downtrend(16, 130);
    const star = [
      bar("2026-02-01", 100, 100.3, 93.8, 94.4),
      bar("2026-02-02", 94.1, 94.6, 93.4, 93.8),
      bar("2026-02-03", 94.6, 99.7, 94.3, 99.1, 2_400_000),
    ];
    const sr = detectSrMarks([...prefix, ...star]);
    expect(sr.every((m) => m.kind === "level" || m.kind === "trend")).toBe(true);
    expect(sr.map((m) => m.name)).not.toContain("Morning Star");
  });
});
