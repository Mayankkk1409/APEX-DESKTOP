import { describe, expect, it } from "vitest";
import {
  computeSeries,
  layoutPlot,
  overlayChromePad,
  overlayLayout,
  PIVOT_ORANGE,
  viewportBars,
  visiblePivotRows,
} from "./plotChart";
import { pivotCaption, pivotLadder, pivotPoints, type OhlcBar } from "./ta";

function bars(n = 80, start = 200): OhlcBar[] {
  const out: OhlcBar[] = [];
  let px = start;
  for (let i = 0; i < n; i++) {
    const o = px;
    const c = px + ((i % 5) - 2) * 0.6;
    out.push({
      t: `2026-03-${String((i % 28) + 1).padStart(2, "0")}`,
      o,
      h: Math.max(o, c) + 0.8,
      l: Math.min(o, c) - 0.8,
      c,
      v: 1_000_000 + i * 1000,
    });
    px = c;
  }
  return out;
}

describe("pivot overlay styling", () => {
  it("ladders R5 through S5 with P labels and orange captions", () => {
    const p = pivotPoints(210, 190, 200);
    const ladder = pivotLadder(p);
    expect(ladder.map((r) => r.label)).toEqual(["R5", "R4", "R3", "R2", "R1", "P", "S1", "S2", "S3", "S4", "S5"]);
    expect(p.r5).toBeGreaterThan(p.r4);
    expect(p.r4).toBeGreaterThan(p.r3);
    expect(p.s5).toBeLessThan(p.s4);
    expect(pivotCaption("R5", 261.22)).toBe("R5 (261.22)");
    expect(pivotCaption("P", 201.72)).toBe("P (201.72)");
    expect(PIVOT_ORANGE.toLowerCase()).toBe("#ff9800");
  });

  it("visible pivots prefer core R1–S3 inside the price range", () => {
    const p = pivotPoints(210, 190, 200);
    const near = visiblePivotRows(p, 195, 210);
    expect(near.every((r) => r.price >= 195 && r.price <= 210)).toBe(true);
    expect(near.some((r) => r.label === "P")).toBe(true);
    expect(near.every((r) => !["R5", "S5"].includes(r.label) || near.length <= 7)).toBe(true);
    const none = visiblePivotRows(p, 1000, 1100);
    expect(none).toEqual([]);
  });
});

describe("overlay layout leaves full MACD + RSI panes", () => {
  it("clips the desk price pane above the oscillator stack", () => {
    const pad = overlayChromePad("desk");
    expect(pad.osc).toBeGreaterThanOrEqual(0.35);
    expect(pad.l).toBeGreaterThanOrEqual(50);
    const series = computeSeries(bars());
    const layout = overlayLayout(bars(), series, 1200, 800, "desk");
    const body = 800 - pad.t - pad.time;
    expect(layout.priceBottom - layout.priceTop).toBeLessThan(body * 0.7);
    expect(layout.priceBottom).toBeLessThan(800 * 0.72);
  });

  it("frozen scan also reserves oscillator height", () => {
    const pad = overlayChromePad("frozen");
    expect(pad.osc).toBeGreaterThanOrEqual(0.35);
    const series = computeSeries(bars());
    const layout = overlayLayout(bars(), series, 1100, 640, "frozen");
    expect(layout.priceBottom).toBeLessThan(640 * 0.72);
  });
});

describe("snapshot plot layout", () => {
  it("reserves distinct price / MACD / RSI panes", () => {
    const series = computeSeries(bars());
    const layout = layoutPlot(bars(), series, 1280, 760, "snapshot");
    expect(layout.priceBottom).toBeLessThan(layout.macdTop);
    expect(layout.macdBottom).toBeLessThan(layout.rsiTop);
    expect(layout.rsiBottom - layout.rsiTop).toBeGreaterThan(40);
    expect(layout.priceBottom - layout.priceTop).toBeGreaterThan(layout.macdBottom - layout.macdTop);
  });
});

describe("viewportBars locks the visible window", () => {
  it("returns a trailing slice shorter than the full series on a wide desk", () => {
    const all = bars(400);
    const { start, bars: visible } = viewportBars(all, 1100, "desk");
    expect(visible.length).toBeLessThan(all.length);
    expect(visible.length).toBeGreaterThanOrEqual(36);
    expect(start).toBe(all.length - visible.length);
    expect(visible[0].t).toBe(all[start].t);
    expect(visible[visible.length - 1].t).toBe(all[all.length - 1].t);
  });

  it("honors an explicit from/to lock instead of the trailing estimate", () => {
    const all: OhlcBar[] = [];
    let px = 200;
    for (let i = 0; i < 200; i++) {
      const o = px;
      const c = px + 0.2;
      all.push({
        t: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
        o,
        h: Math.max(o, c) + 0.5,
        l: Math.min(o, c) - 0.5,
        c,
        v: 1_000_000,
      });
      px = c;
    }
    const from = all[40].t;
    const to = all[90].t;
    const { bars: visible } = viewportBars(all, 1100, "desk", { from, to });
    expect(visible).toHaveLength(51);
    expect(visible[0].t).toBe(from);
    expect(visible[visible.length - 1].t).toBe(to);
  });
});
