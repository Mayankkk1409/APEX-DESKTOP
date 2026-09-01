import { describe, expect, it } from "vitest";
import { buildAnalysisCards } from "./analysisCards";
import {
  catalystIsDrawable,
  emaCrossPoint,
  macdCrossPoint,
  patternEnclosingBox,
  patternEnclosingCircle,
  resolveChartHighlight,
  resolvePatternMarkShape,
  scoreTier,
} from "./chartHighlight";
import { computeSeries, layoutPlot } from "./plotChart";
import { catalystIsDrawableOnChart, detectCatalysts, isMorningStar, patternUsesBoxMark, type Catalyst } from "./patterns";
import type { OhlcBar } from "./ta";

function trend(n: number, start = 180, step = 0.45): OhlcBar[] {
  const out: OhlcBar[] = [];
  let px = start;
  for (let i = 0; i < n; i++) {
    const o = px;
    const c = px + step;
    out.push({
      t: `2026-04-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z`,
      o,
      h: Math.max(o, c) + 0.4,
      l: Math.min(o, c) - 0.35,
      c,
      v: 800_000 + i * 2500,
    });
    px = c;
  }
  return out;
}

/** Force a textbook morning star at the end of the series. */
function withMorningStar(base: OhlcBar[]): OhlcBar[] {
  const bars = base.map((b) => ({ ...b }));
  const i = bars.length - 1;
  const a = bars[i - 2];
  const m = bars[i - 1];
  const c = bars[i];
  // Long bearish body
  a.o = 110;
  a.c = 100;
  a.h = 111;
  a.l = 99;
  // Small midpoint below
  m.o = 99.2;
  m.c = 98.8;
  m.h = 99.5;
  m.l = 98.5;
  // Bullish close through first midpoint
  c.o = 99;
  c.c = 106;
  c.h = 107;
  c.l = 98.7;
  expect(isMorningStar(a, m, c, 8)).toBe(true);
  return bars;
}

describe("scoreTier", () => {
  it("blocks at or below 50", () => {
    expect(scoreTier(49)).toBe("blocked");
    expect(scoreTier(50)).toBe("blocked");
  });

  it("cautions between 51 and threshold-1", () => {
    expect(scoreTier(51, 85)).toBe("caution");
    expect(scoreTier(84, 85)).toBe("caution");
  });

  it("auto-execs at user threshold and above", () => {
    expect(scoreTier(85, 85)).toBe("auto_exec");
    expect(scoreTier(90, 85)).toBe("auto_exec");
    expect(scoreTier(72, 72)).toBe("auto_exec");
  });
});

describe("resolveChartHighlight", () => {
  const bars = trend(90);
  const series = computeSeries(bars);
  const layout = layoutPlot(bars, series, 1280, 760, "snapshot");
  const { cards, catalysts } = buildAnalysisCards("AAPL", "1D", bars);

  it("glows EMA 9/21/50 on the EMA study card only", () => {
    const ema = cards.find((c) => c.id === "study-ema");
    const bb = cards.find((c) => c.id === "study-bb");
    const emaHl = resolveChartHighlight(ema, bars, series, layout, catalysts);
    const bbHl = resolveChartHighlight(bb, bars, series, layout, catalysts);
    expect(emaHl?.glowLines?.length).toBe(3);
    expect(bbHl?.glowLines?.length).toBeGreaterThan(0);
  });

  it("does not glow SuperTrend, SMA, pivots, or S/R cards", () => {
    const st = cards.find((c) => c.id === "study-supertrend");
    const sma = cards.find((c) => c.id === "study-sma50");
    const piv = cards.find((c) => c.id === "study-pivots");
    const sr = cards.find((c) => c.id === "study-sr");
    expect(resolveChartHighlight(st, bars, series, layout, catalysts)).toBeNull();
    expect(resolveChartHighlight(sma, bars, series, layout, catalysts)).toBeNull();
    expect(resolveChartHighlight(piv, bars, series, layout, catalysts)).toBeNull();
    expect(resolveChartHighlight(sr, bars, series, layout, catalysts)).toBeNull();
  });

  it("returns a single pattern mark for candle catalyst cards", () => {
    const cats = detectCatalysts(bars, series);
    const candle = cats.find((c) => c.kind === "candle");
    if (!candle) return;
    const catCard = cards.find((c) => c.markId === candle.id) ?? {
      id: `cat-${candle.id}`,
      name: candle.name,
      kind: "catalyst" as const,
      bias: candle.bias,
      body: candle.explain,
      markId: candle.id,
    };
    const hl = resolveChartHighlight(catCard, bars, series, layout, cats);
    expect(hl?.mark).toBeTruthy();
    expect(hl?.glowLines ?? []).toHaveLength(0);
  });

  it("does not highlight SuperTrend flip or S/R trendline catalysts", () => {
    const stFlip: Catalyst = {
      id: "supertrend-bullish-flip-80",
      name: "SuperTrend bullish flip",
      bias: "bullish",
      kind: "momentum",
      barIndex: 80,
      price: bars[80].c,
      explain: "flip",
      confidence: 0.9,
    };
    const srRay: Catalyst = {
      id: "ascending-support-10",
      name: "Ascending support trendline",
      bias: "bullish",
      kind: "trend",
      barIndex: 10,
      barEnd: 80,
      price: 100,
      price2: 120,
      explain: "ray",
      confidence: 0.7,
    };
    expect(catalystIsDrawable(stFlip)).toBe(false);
    expect(catalystIsDrawable(srRay)).toBe(false);
    expect(
      resolveChartHighlight(
        { id: "c1", name: stFlip.name, kind: "catalyst", bias: "bullish", body: "", markId: stFlip.id },
        bars,
        series,
        layout,
        [stFlip],
      ),
    ).toBeNull();
    expect(
      resolveChartHighlight(
        { id: "c2", name: srRay.name, kind: "catalyst", bias: "bullish", body: "", markId: srRay.id },
        bars,
        series,
        layout,
        [srRay],
      ),
    ).toBeNull();
  });

  it("uses a rectangle for head & shoulders and bull flag catalysts", () => {
    const hs: Catalyst = {
      id: "head-shoulders-10",
      name: "Head & Shoulders",
      bias: "bearish",
      kind: "structure",
      barIndex: 10,
      barEnd: 40,
      price: 115,
      price2: 125,
      explain: "test",
      confidence: 0.9,
    };
    const flag: Catalyst = {
      id: "bull-flag-50",
      name: "Bull Flag",
      bias: "bullish",
      kind: "structure",
      barIndex: 50,
      barEnd: 85,
      price: 190,
      price2: 205,
      explain: "test",
      confidence: 0.74,
    };
    expect(patternUsesBoxMark(hs)).toBe(true);
    expect(patternUsesBoxMark(flag)).toBe(true);
    expect(catalystIsDrawableOnChart(hs)).toBe(true);
    expect(catalystIsDrawableOnChart(flag)).toBe(true);

    const hsMark = resolvePatternMarkShape(bars, layout, hs);
    const flagMark = resolvePatternMarkShape(bars, layout, flag);
    expect(hsMark?.kind).toBe("box");
    expect(flagMark?.kind).toBe("box");

    const hsHl = resolveChartHighlight(
      { id: "cat-hs", name: hs.name, kind: "catalyst", bias: "bearish", body: "", markId: hs.id },
      bars,
      series,
      layout,
      [hs],
    );
    expect(hsHl?.mark?.kind).toBe("box");
    if (hsMark?.kind === "box") {
      expect(hsMark.x).toBeCloseTo(layout.x(10) - layout.candleW / 2, 5);
      expect(hsMark.x + hsMark.w).toBeCloseTo(layout.x(40) + layout.candleW / 2, 5);
    }
  });

  it("centers the EMA 9/21 cross mark on the price pane for the EMA study card", () => {
    const barsX = trend(60, 100, 0.3);
    const seriesX = computeSeries(barsX);
    const ema9 = seriesX.ema9.slice();
    const ema21 = seriesX.ema21.slice();
    for (let i = 0; i < ema9.length; i++) {
      ema9[i] = i < 51 ? 98 : 102;
      ema21[i] = 100;
    }
    seriesX.ema9 = ema9;
    seriesX.ema21 = ema21;

    const pt = emaCrossPoint(seriesX, 51);
    expect(pt).not.toBeNull();
    expect(pt!.iFrac).toBeCloseTo(50.5, 5);
    expect(pt!.value).toBeCloseTo(100, 5);

    const layoutX = layoutPlot(barsX, seriesX, 1280, 760, "snapshot");
    const emaCard = { id: "study-ema", name: "EMA", kind: "study" as const, bias: "neutral" as const, body: "" };
    const hl = resolveChartHighlight(emaCard, barsX, seriesX, layoutX, []);
    expect(hl?.glowLines?.length).toBe(3);
    expect(hl?.mark?.kind).toBe("circle");
    if (hl?.mark?.kind !== "circle") return;
    expect(hl.mark.cx).toBeCloseTo(layoutX.x(pt!.iFrac), 5);
    expect(hl.mark.cy).toBeCloseTo(layoutX.y(pt!.value), 5);
  });

  it("marks EMA 9/21 bullish cross catalyst cards on the price pane", () => {
    const barsX = trend(60, 100, 0.3);
    const seriesX = computeSeries(barsX);
    const ema9 = seriesX.ema9.slice();
    const ema21 = seriesX.ema21.slice();
    for (let i = 0; i < ema9.length; i++) {
      ema9[i] = i < 51 ? 98 : 102;
      ema21[i] = 100;
    }
    seriesX.ema9 = ema9;
    seriesX.ema21 = ema21;
    const layoutX = layoutPlot(barsX, seriesX, 1280, 760, "snapshot");
    const pt = emaCrossPoint(seriesX, 51)!;

    const emaCat: Catalyst = {
      id: "ema-9-21-bullish-cross-51",
      name: "EMA 9/21 bullish cross",
      bias: "bullish",
      kind: "momentum",
      barIndex: 51,
      price: barsX[51].c,
      explain: "test",
      confidence: 0.84,
    };
    expect(catalystIsDrawableOnChart(emaCat)).toBe(true);
    const hl = resolveChartHighlight(
      { id: "cat-ema", name: emaCat.name, kind: "catalyst", bias: "bullish", body: "", markId: emaCat.id },
      barsX,
      seriesX,
      layoutX,
      [emaCat],
    );
    expect(hl?.mark?.kind).toBe("circle");
    if (hl?.mark?.kind !== "circle") return;
    expect(hl.mark.cx).toBeCloseTo(layoutX.x(pt.iFrac), 5);
    expect(hl.mark.cy).toBeCloseTo(layoutX.y(pt.value), 5);
  });

  it("clears highlight when card has no linked study", () => {
    const windowCard = cards.find((c) => c.id === "study-window");
    expect(resolveChartHighlight(windowCard, bars, series, layout, catalysts)).toBeNull();
  });

  it("MACD study card can include crossover mark", () => {
    const macd = cards.find((c) => c.id === "study-macd");
    const hl = resolveChartHighlight(macd, bars, series, layout, catalysts);
    expect(hl?.glowPanes?.length).toBe(1);
  });

  it("pattern box spans the full detected bar range for structures", () => {
    const hs: Catalyst = {
      id: "head-shoulders-box",
      name: "Head & Shoulders",
      bias: "bearish",
      kind: "structure",
      barIndex: 5,
      barEnd: 15,
      price: 120,
      price2: 130,
      explain: "test",
      confidence: 0.9,
    };
    const mark = patternEnclosingBox(bars, layout, hs);
    expect(mark?.kind).toBe("box");
    if (mark?.kind !== "box") return;
    expect(mark.x).toBeCloseTo(layout.x(5) - layout.candleW / 2, 5);
    expect(mark.x + mark.w).toBeCloseTo(layout.x(15) + layout.candleW / 2, 5);
  });

  it("pattern circle contains every bar that forms the pattern", () => {
    const msBars = withMorningStar(trend(40, 105, -0.2));
    const msSeries = computeSeries(msBars);
    const msLayout = layoutPlot(msBars, msSeries, 1280, 760, "snapshot");
    const i1 = msBars.length - 1;
    const i0 = i1 - 2;
    const cat: Catalyst = {
      id: "morning-star-test",
      name: "Morning Star",
      bias: "bullish",
      kind: "candle",
      barIndex: i0,
      barEnd: i1,
      price: Math.min(msBars[i0].l, msBars[i0 + 1].l, msBars[i1].l),
      price2: Math.max(msBars[i0].h, msBars[i0 + 1].h, msBars[i1].h),
      explain: "test",
      confidence: 0.93,
    };
    const mark = patternEnclosingCircle(msBars, msLayout, cat);
    expect(mark?.kind).toBe("circle");
    if (mark?.kind !== "circle") return;
    for (let i = i0; i <= i1; i++) {
      const b = msBars[i];
      const left = msLayout.x(i) - msLayout.candleW / 2;
      const right = msLayout.x(i) + msLayout.candleW / 2;
      const top = msLayout.y(b.h);
      const bot = msLayout.y(b.l);
      for (const [px, py] of [
        [left, top],
        [right, top],
        [left, bot],
        [right, bot],
      ] as const) {
        const dx = px - mark.cx;
        const dy = py - mark.cy;
        expect(Math.sqrt(dx * dx + dy * dy)).toBeLessThanOrEqual(mark.r + 0.05);
      }
    }
  });

  it("centers the MACD cross mark on the exact line/signal intersection", () => {
    // Build a clear cross: line below signal then above.
    const barsX = trend(60, 100, 0.3);
    const seriesX = computeSeries(barsX);
    // Mutate MACD arrays to force a known cross between indices 50 and 51.
    const line = seriesX.macd.line.slice();
    const signal = seriesX.macd.signal.slice();
    for (let i = 0; i < line.length; i++) {
      line[i] = i < 51 ? -1 : 1;
      signal[i] = 0;
    }
    seriesX.macd = { ...seriesX.macd, line, signal, histogram: line.map((v, i) => v - signal[i]) };
    const pt = macdCrossPoint(seriesX, 51);
    expect(pt).not.toBeNull();
    expect(pt!.iFrac).toBeCloseTo(50.5, 5);
    expect(pt!.value).toBeCloseTo(0, 5);

    const layoutX = layoutPlot(barsX, seriesX, 1280, 760, "snapshot");
    const { lo, hi } = (() => {
      const hist = seriesX.macd.histogram.filter(Number.isFinite);
      const macdLine = seriesX.macd.line.filter(Number.isFinite);
      const sigLine = seriesX.macd.signal.filter(Number.isFinite);
      return { lo: Math.min(...hist, ...macdLine, ...sigLine, 0), hi: Math.max(...hist, ...macdLine, ...sigLine, 0) };
    })();
    const macdCard = { id: "study-macd", name: "MACD", kind: "study" as const, bias: "neutral" as const, body: "" };
    const hl = resolveChartHighlight(macdCard, barsX, seriesX, layoutX, []);
    expect(hl?.mark?.kind).toBe("circle");
    if (hl?.mark?.kind !== "circle") return;
    expect(hl.mark.cx).toBeCloseTo(layoutX.x(pt!.iFrac), 5);
    expect(hl.mark.cy).toBeCloseTo(layoutX.yMacd(pt!.value, lo, hi), 5);
  });
});
