import { describe, expect, it } from "vitest";
import { barsInRange, describeWindow } from "../chartCapture";
import { analysisSeriesBars, buildAnalysisCards } from "./analysisCards";
import { detectHorizontalLevels } from "./levels";
import { computeSeries } from "./plotChart";
import { computeStudies, emaSeries, macdSeries, rsiSeries } from "./studies";
import type { OhlcBar } from "./ta";

function series(n: number, start = 100): OhlcBar[] {
  const out: OhlcBar[] = [];
  for (let i = 0; i < n; i++) {
    const c = start + Math.sin(i / 9) * 6 + i * 0.11;
    const o = start + Math.sin((i - 1) / 9) * 6 + (i - 1) * 0.11;
    out.push({
      t: new Date(Date.UTC(2025, 0, 1 + i)).toISOString(),
      o,
      h: Math.max(o, c) + 1.1,
      l: Math.min(o, c) - 1.1,
      c,
      v: 1_000_000 + i * 913,
    });
  }
  return out;
}

describe("visible-range slicing", () => {
  const all = series(300);

  it("keeps only the bars inside the captured window", () => {
    const window = all.slice(120, 200);
    const sliced = barsInRange(all, window[0].t, window[window.length - 1].t);
    expect(sliced).toHaveLength(80);
    expect(sliced[0].t).toBe(all[120].t);
    expect(sliced[sliced.length - 1].t).toBe(all[199].t);
  });

  it("falls back to an empty window when the range is unparseable", () => {
    expect(barsInRange(all, "not-a-date", "also-not")).toHaveLength(0);
    expect(barsInRange(all, "", "")).toHaveLength(0);
  });

  it("describes the window so the desk can verify it", () => {
    const window = all.slice(10, 40);
    expect(describeWindow(window, window[0].t, window[window.length - 1].t)).toBe("30 bars · 2025-01-11 → 2025-02-09");
    expect(describeWindow([], "", "")).toBe("no bars captured");
  });
});

describe("analysis evaluates the captured window with warm-up but no look-ahead", () => {
  const all = series(300);
  const window = all.slice(220, 280);

  it("truncates the evaluation series at the last visible bar", () => {
    const evalBars = analysisSeriesBars(window, all);
    expect(evalBars).toHaveLength(280);
    expect(evalBars[evalBars.length - 1].t).toBe(window[window.length - 1].t);
  });

  it("falls back to the window itself when no context is supplied", () => {
    expect(analysisSeriesBars(window, [])).toBe(window);
    expect(analysisSeriesBars(window, series(20, 500))).toBe(window);
  });

  it("reports values that reproduce from those exact bars", () => {
    const { series: s } = buildAnalysisCards("AAPL", "1D", window, { contextBars: all });
    const last = window.length - 1;
    const evalBars = analysisSeriesBars(window, all);
    const closes = evalBars.map((b) => b.c);
    const e = evalBars.length - 1;

    expect(s.ema9[last]).toBeCloseTo(emaSeries(closes, 9)[e] as number, 10);
    expect(s.ema21[last]).toBeCloseTo(emaSeries(closes, 21)[e] as number, 10);
    expect(s.ema200[last]).toBeCloseTo(emaSeries(closes, 200)[e] as number, 10);
    expect(s.rsi[last]).toBeCloseTo(rsiSeries(closes, 14)[e] as number, 10);
    expect(s.macd.line[last]).toBeCloseTo(macdSeries(closes, 12, 26, 9).line[e] as number, 10);
    expect(s.macd.signal[last]).toBeCloseTo(macdSeries(closes, 12, 26, 9).signal[e] as number, 10);
    expect(s.macd.histogram[last]).toBeCloseTo(macdSeries(closes, 12, 26, 9).histogram[e] as number, 10);

    const studies = computeStudies(evalBars);
    expect(s.bb.mid[last]).toBeCloseTo(studies.bb.basis[e] as number, 10);
    expect(s.bb.upper[last]).toBeCloseTo(studies.bb.upper[e] as number, 10);
    expect(s.bb.lower[last]).toBeCloseTo(studies.bb.lower[e] as number, 10);
  });

  it("carousel prose quotes the same EMA/MACD/RSI/BB figures as the series", () => {
    const { cards, series: s } = buildAnalysisCards("AAPL", "1D", window, { contextBars: all });
    const last = window.length - 1;
    const emaCard = cards.find((c) => c.id === "study-ema");
    const macdCard = cards.find((c) => c.id === "study-macd");
    const rsiCard = cards.find((c) => c.id === "study-rsi");
    const bbCard = cards.find((c) => c.id === "study-bb");
    expect(emaCard?.body).toContain(s.ema9[last].toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }));
    expect(macdCard?.body).toMatch(new RegExp(s.macd.line[last].toFixed(4).replace(".", "\\.")));
    expect(rsiCard?.body).toMatch(new RegExp(s.rsi[last].toFixed(2).replace(".", "\\.")));
    expect(bbCard?.body).toContain(s.bb.upper[last].toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }));
  });

  it("quotes the same numbers the chart legend shows for the same bars", () => {
    const evalBars = analysisSeriesBars(window, all);
    const legend = computeStudies(evalBars);
    const { series: s } = buildAnalysisCards("AAPL", "1D", window, { contextBars: all });
    const last = window.length - 1;
    const e = evalBars.length - 1;
    expect(s.ema50[last]).toBeCloseTo(legend.ema[50][e] as number, 10);
    expect(s.bb.upper[last]).toBeCloseTo(legend.bb.upper[e] as number, 10);
    expect(s.st[last].value).toBeCloseTo(legend.supertrend.value[e] as number, 10);
  });

  it("leads with a card that states the captured window", () => {
    const { cards } = buildAnalysisCards("AAPL", "1D", window, { contextBars: all });
    const first = cards[0];
    expect(first.id).toBe("study-window");
    expect(first.body).toContain(`${window.length} visible bars`);
    expect(first.body).toContain(window[0].t);
    expect(first.body).toContain(window[window.length - 1].t);
  });

  it("marks studies that cannot be defined on a short window instead of faking them", () => {
    const short = series(60);
    const { series: s, cards } = buildAnalysisCards("AAPL", "1D", short);
    expect(Number.isFinite(s.ema200[short.length - 1])).toBe(false);
    const ema = cards.find((c) => c.id === "study-ema");
    expect(ema?.body).toContain("n/a");
  });

  it("uses daily bars for pivots when the chart is intraday", () => {
    const daily = series(80, 250);
    const intraday = series(120, 250);
    const { series: s } = buildAnalysisCards("AAPL", "5m", intraday, { dailyBars: daily });
    expect(s.pivots).not.toBeNull();
    const prevDay = daily[daily.length - 2];
    expect(s.pivots?.pp).toBeCloseTo((prevDay.h + prevDay.l + prevDay.c) / 3, 10);
  });
});

describe("support / resistance detection draws horizontals only", () => {
  it("returns priced horizontal levels, never sloped geometry", () => {
    const levels = detectHorizontalLevels(series(240));
    for (const lv of levels) {
      expect(Number.isFinite(lv.price)).toBe(true);
      expect(["support", "resistance"]).toContain(lv.kind);
      expect(lv.touches).toBeGreaterThanOrEqual(2);
      expect(Object.keys(lv).sort()).toEqual(["id", "kind", "price", "touches"]);
    }
  });

  it("never returns more than the requested maximum", () => {
    expect(detectHorizontalLevels(series(300), 3).length).toBeLessThanOrEqual(3);
  });

  it("stays empty on too little history", () => {
    expect(detectHorizontalLevels(series(10))).toEqual([]);
  });

  it("puts supports at or below spot and resistances at or above it", () => {
    const bars = series(260);
    const last = bars[bars.length - 1].c;
    for (const lv of detectHorizontalLevels(bars)) {
      if (lv.kind === "support") expect(lv.price).toBeLessThanOrEqual(last);
      else expect(lv.price).toBeGreaterThanOrEqual(last);
    }
  });
});

describe("computeSeries edge cases", () => {
  it("does not throw on an empty or single-bar series", () => {
    expect(() => computeSeries([])).not.toThrow();
    expect(() => computeSeries(series(1))).not.toThrow();
  });

  it("reports NaN rather than an invented value during warm-up", () => {
    const s = computeSeries(series(30));
    expect(Number.isFinite(s.ema200[29])).toBe(false);
    expect(Number.isFinite(s.ema9[29])).toBe(true);
  });
});
