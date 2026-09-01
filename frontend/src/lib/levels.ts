/**
 * Horizontal support / resistance only.
 *
 * The previous overlay also fitted diagonal rays through swing points and drew
 * them straight across the price pane, which is where the stray green diagonal
 * came from. Levels are horizontals — anything sloped has to be drawn by the
 * user with the trendline tool.
 */

import type { OhlcBar } from "./ta";

export type HorizontalLevel = {
  id: string;
  price: number;
  kind: "support" | "resistance";
  touches: number;
};

type Swing = { i: number; v: number };

function swings(values: number[], span: number, kind: "high" | "low"): Swing[] {
  const out: Swing[] = [];
  for (let i = span; i < values.length - span; i++) {
    const v = values[i];
    let ok = true;
    for (let k = 1; k <= span && ok; k++) {
      ok = kind === "high" ? v >= values[i - k] && v >= values[i + k] : v <= values[i - k] && v <= values[i + k];
    }
    if (ok) out.push({ i, v });
  }
  return out;
}

function cluster(points: Swing[], tolerance: number): { price: number; touches: number }[] {
  const used = new Set<number>();
  const out: { price: number; touches: number }[] = [];
  for (let i = 0; i < points.length; i++) {
    if (used.has(i)) continue;
    const group = [points[i]];
    used.add(i);
    for (let j = i + 1; j < points.length; j++) {
      if (used.has(j)) continue;
      if (Math.abs(points[j].v - points[i].v) <= tolerance) {
        group.push(points[j]);
        used.add(j);
      }
    }
    if (group.length < 2) continue;
    out.push({ price: group.reduce((s, g) => s + g.v, 0) / group.length, touches: group.length });
  }
  return out;
}

/** At most `max` horizontal levels, ranked by touch count then proximity to spot. */
export function detectHorizontalLevels(bars: OhlcBar[], max = 4): HorizontalLevel[] {
  if (bars.length < 20) return [];
  const last = bars[bars.length - 1].c;
  const tolerance = last * 0.004;
  const highs = cluster(
    swings(
      bars.map((b) => b.h),
      3,
      "high",
    ),
    tolerance,
  );
  const lows = cluster(
    swings(
      bars.map((b) => b.l),
      3,
      "low",
    ),
    tolerance,
  );

  const all: HorizontalLevel[] = [
    ...lows
      .filter((g) => g.price <= last)
      .map((g) => ({ id: `s-${g.price.toFixed(4)}`, price: g.price, kind: "support" as const, touches: g.touches })),
    ...highs
      .filter((g) => g.price >= last)
      .map((g) => ({ id: `r-${g.price.toFixed(4)}`, price: g.price, kind: "resistance" as const, touches: g.touches })),
  ];

  return all
    .sort((a, b) => b.touches - a.touches || Math.abs(a.price - last) - Math.abs(b.price - last))
    .slice(0, max);
}
