import { describe, expect, it } from "vitest";
import { buildAnalysisCards } from "./analysisCards";
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

const REQUIRED = [/EMA/i, /MACD/i, /RSI/i, /Bollinger/i, /Pivot/i, /Support/i, /SuperTrend/i, /Volume/i];

describe("buildAnalysisCards", () => {
  it("always returns at least 9 cards covering the required studies", () => {
    const { cards } = buildAnalysisCards("AAPL", "1D", trend(90));
    expect(cards.length).toBeGreaterThanOrEqual(9);
    for (const re of REQUIRED) {
      expect(cards.some((c) => re.test(c.name))).toBe(true);
    }
    const pivot = cards.find((c) => /Pivot/i.test(c.name));
    expect(pivot?.body).toMatch(/R5/);
    expect(pivot?.body).toMatch(/S5/);
    expect(pivot?.body).toMatch(/P = \(H\+L\+C\)\/3|central pivot/i);
  });

  it("does not invent a morning star on a one-way advance", () => {
    const { cards } = buildAnalysisCards("AAPL", "1D", trend(60, 100, 0.7));
    expect(cards.map((c) => c.name)).not.toContain("Morning Star");
  });

  it("scan without bars still exposes 9 named study shells", () => {
    const { cards } = buildAnalysisCards("SPX", "1D", []);
    expect(cards.length).toBeGreaterThanOrEqual(9);
    for (const re of REQUIRED) {
      expect(cards.some((c) => re.test(c.name))).toBe(true);
    }
    expect(cards.every((c) => /Waiting on OHLC|no pattern/i.test(c.body))).toBe(true);
  });
});
