import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { autoExecEligibilityLine, autoSubmitArms, manualConfirmationNote, orderPlacement } from "./riskReview";

const here = dirname(fileURLToPath(import.meta.url));

describe("autoSubmitArms", () => {
  it("arms at 36 when the saved minimum is 35 and does not arm at 34", () => {
    expect(
      autoSubmitArms({ toggleOn: true, composite: 36, threshold: 35, definedRisk: true }),
    ).toBe(true);
    expect(
      autoSubmitArms({ toggleOn: true, composite: 34, threshold: 35, definedRisk: true }),
    ).toBe(false);
  });

  it("does not arm at 72 when the saved minimum is 85", () => {
    expect(
      autoSubmitArms({ toggleOn: true, composite: 72, threshold: 85, definedRisk: true }),
    ).toBe(false);
  });

  it("stays off when the global toggle is off", () => {
    expect(
      autoSubmitArms({ toggleOn: false, composite: 90, threshold: 35, definedRisk: true }),
    ).toBe(false);
  });

  it("stays off for undefined risk", () => {
    expect(
      autoSubmitArms({ toggleOn: true, composite: 90, threshold: 35, definedRisk: false }),
    ).toBe(false);
  });
});

describe("orderPlacement", () => {
  const legs = { toggleOn: true, definedRisk: true, hasLegs: true };

  it("auto-submits on acknowledgement above the saved minimum", () => {
    expect(orderPlacement({ ...legs, composite: 71, threshold: 70 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      note: null,
    });
  });

  it("auto-submits on acknowledgement when the score equals the saved minimum", () => {
    expect(orderPlacement({ ...legs, composite: 70, threshold: 70 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      note: null,
    });
  });

  it("keeps Place Trade enabled below the saved minimum with a neutral note", () => {
    const placement = orderPlacement({ ...legs, composite: 62, threshold: 70 });
    expect(placement.autoSubmitOnAck).toBe(false);
    expect(placement.placeTradeEnabled).toBe(true);
    expect(placement.note).toBe(
      "Manual confirmation required (score 62 vs. your auto-execute minimum 70).",
    );
    expect(placement.note).not.toContain("BELOW EXECUTION THRESHOLD");
    expect(manualConfirmationNote(62, 70)).toBe(placement.note);
  });

  it("arms acknowledgement at 66 when the saved minimum is 40", () => {
    expect(orderPlacement({ ...legs, composite: 66, threshold: 40 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      note: null,
    });
    expect(autoExecEligibilityLine(66, 40)).toBe(
      "Composite score 66 · Your auto-execute minimum 40 · Auto-execute eligible",
    );
  });

  it("keeps Place Trade when the toggle is off even if the score clears the minimum", () => {
    expect(orderPlacement({ ...legs, toggleOn: false, composite: 66, threshold: 40 })).toEqual({
      autoSubmitOnAck: false,
      placeTradeEnabled: true,
      note: "Auto-execution is off.",
    });
  });

  it("does not block a score of 72 when the saved minimum is 40", () => {
    expect(orderPlacement({ ...legs, composite: 72, threshold: 40 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      note: null,
    });
    expect(orderPlacement({ ...legs, toggleOn: false, composite: 72, threshold: 40 })).toEqual({
      autoSubmitOnAck: false,
      placeTradeEnabled: true,
      note: "Auto-execution is off.",
    });
  });

  it("does not contain the forbidden blocker string", () => {
    const files = [
      resolve(here, "riskReview.ts"),
      resolve(here, "../pages/DeepScan.tsx"),
      resolve(here, "../pages/Settings.tsx"),
      resolve(here, "userSettings.ts"),
    ];
    for (const file of files) {
      expect(readFileSync(file, "utf8")).not.toContain("BELOW EXECUTION THRESHOLD");
    }
  });
});
