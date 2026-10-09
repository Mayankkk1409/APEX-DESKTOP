import { describe, expect, it } from "vitest";
import { poly } from "./ChartOverlay";

describe("poly", () => {
  it("connects contiguous finite points with M then L", () => {
    const d = poly([1, 2, 3], [4, 5, 6]);
    expect(d.startsWith("M")).toBe(true);
    expect(d.match(/M/g)).toHaveLength(1);
    expect(d.match(/L/g)).toHaveLength(2);
  });

  it("lifts the pen across a non-finite gap", () => {
    const d = poly([1, 2, 3, 4], [4, Number.NaN, 6, 7]);
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d.match(/L/g)).toHaveLength(1);
  });
});
