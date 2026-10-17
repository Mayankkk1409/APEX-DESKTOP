import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  autoExecEligibilityLine,
  autoSubmitArms,
  blockedEligibilityLine,
  orderPlacement,
  thesisCheckboxState,
} from "./riskReview";

const here = dirname(fileURLToPath(import.meta.url));

describe("autoSubmitArms", () => {
  it("arms at 36 when the saved minimum is 35 and does not arm at 34", () => {
    expect(
      autoSubmitArms({
        toggleOn: true,
        serverAutoSubmit: true,
        executable: true,
        validationPassed: true,
        composite: 36,
        threshold: 35,
        definedRisk: true,
      }),
    ).toBe(true);
    expect(
      autoSubmitArms({
        serverAutoSubmit: true,
        executable: true,
        validationPassed: true,
        composite: 34,
        threshold: 35,
        definedRisk: true,
      }),
    ).toBe(false);
  });

  it("does not arm at 72 when the saved minimum is 85", () => {
    expect(
      autoSubmitArms({
        serverAutoSubmit: true,
        executable: true,
        validationPassed: true,
        composite: 72,
        threshold: 85,
        definedRisk: true,
      }),
    ).toBe(false);
  });

  it("still arms when the browser toggle defaults off and the server flag is true", () => {
    expect(
      autoSubmitArms({
        toggleOn: false,
        serverAutoSubmit: true,
        composite: 52.8,
        threshold: 40,
        definedRisk: true,
      }),
    ).toBe(true);
  });

  it("stays off when auto-execution is persisted off on the server", () => {
    expect(
      autoSubmitArms({
        serverAutoExecEnabled: false,
        serverAutoSubmit: true,
        composite: 90,
        threshold: 35,
        definedRisk: true,
      }),
    ).toBe(false);
  });

  it("stays off for undefined risk", () => {
    expect(
      autoSubmitArms({ toggleOn: true, composite: 90, threshold: 35, definedRisk: false }),
    ).toBe(false);
  });
});

describe("orderPlacement", () => {
  const legs = {
    toggleOn: true,
    definedRisk: true,
    hasLegs: true,
    serverAutoSubmit: true,
    executable: true,
    validationPassed: true,
    placeable: true,
  };

  it("auto-submits on acknowledgement above the saved minimum", () => {
    expect(orderPlacement({ ...legs, composite: 71, threshold: 70 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
  });

  it("auto-submits on acknowledgement when the score equals the saved minimum", () => {
    expect(orderPlacement({ ...legs, composite: 70, threshold: 70 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
  });

  it("keeps Place Trade when the score is under the minimum even if auto-execute is off", () => {
    const placement = orderPlacement({
      ...legs,
      serverAutoSubmit: false,
      composite: 54.3,
      threshold: 55.6,
      executable: false,
      placeable: true,
      validationPassed: true,
      blockReason: "Composite 54.3. Your minimum 55.6. Not auto-executable: composite is below your minimum.",
    });
    expect(placement.placeTradeEnabled).toBe(true);
    expect(placement.autoSubmitOnAck).toBe(false);
    expect(placement.acknowledgeEnabled).toBe(true);
    expect(placement.overrideRequired).toBe(true);
  });

  it("does not let the thesis checkbox override a hard block", () => {
    const placement = orderPlacement({
      ...legs,
      hardBlocked: true,
      hasLegs: true,
      executable: false,
      placeable: false,
      blockReason: "Leg count 0 does not match the strategy.",
    });
    expect(placement.placeTradeEnabled).toBe(false);
    expect(placement.acknowledgeEnabled).toBe(false);
    expect(placement.overrideRequired).toBe(false);
    expect(placement.autoSubmitOnAck).toBe(false);
    expect(thesisCheckboxState(placement).submitsOnAccept).toBe(false);
  });

  it("requires an explicit override when the displayed score is below the saved minimum", () => {
    const placement = orderPlacement({ ...legs, composite: 49.94, threshold: 50 });
    expect(placement.autoSubmitOnAck).toBe(false);
    expect(placement.overrideRequired).toBe(true);
    expect(placement.placeTradeEnabled).toBe(true);
    expect(placement.note).toContain("Not recommended");
    expect(placement.note).toContain("49.9");
    expect(placement.note).toContain("50.0");
    expect(placement.note).toContain("Proceed at my own risk");
    expect(thesisCheckboxState(placement).submitsOnAccept).toBe(false);
    expect(orderPlacement({ ...legs, composite: 49.96, threshold: 50 }).overrideRequired).toBe(false);
    expect(orderPlacement({ ...legs, composite: 49.96, threshold: 50 }).autoSubmitOnAck).toBe(true);
  });

  it("arms acknowledgement at 66 when the saved minimum is 40", () => {
    expect(orderPlacement({ ...legs, composite: 66, threshold: 40 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
    expect(autoExecEligibilityLine(66, 40)).toBe(
      "Composite 66.0. Your minimum 40.0. Auto-execute eligible.",
    );
  });

  it("shows Acknowledge when the server auto-submits and the browser toggle defaults off", () => {
    expect(
      orderPlacement({
        ...legs,
        toggleOn: false,
        serverAutoSubmit: true,
        composite: 52.8,
        threshold: 40,
      }),
    ).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
    expect(
      orderPlacement({
        ...legs,
        toggleOn: false,
        serverAutoSubmit: true,
        composite: 55.4,
        threshold: 40,
      }).autoSubmitOnAck,
    ).toBe(true);
  });

  it("keeps Place Trade when auto-execution is persisted off on the server", () => {
    expect(
      orderPlacement({
        ...legs,
        toggleOn: false,
        serverAutoExecEnabled: false,
        serverAutoSubmit: true,
        composite: 66,
        threshold: 40,
      }),
    ).toEqual({
      autoSubmitOnAck: false,
      placeTradeEnabled: true,
      acknowledgeEnabled: false,
      note: "Auto-execution is off.",
      overrideRequired: false,
    });
  });

  it("does not block a score of 72 when the saved minimum is 40", () => {
    expect(orderPlacement({ ...legs, composite: 72, threshold: 40 })).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
    expect(
      orderPlacement({
        ...legs,
        toggleOn: false,
        serverAutoSubmit: true,
        composite: 72,
        threshold: 40,
      }),
    ).toEqual({
      autoSubmitOnAck: true,
      placeTradeEnabled: false,
      acknowledgeEnabled: true,
      note: null,
      overrideRequired: false,
    });
  });

  it("does not say auto-execute eligible when the structure is not executable", () => {
    const placement = orderPlacement({
      ...legs,
      serverAutoSubmit: true,
      composite: 62.9,
      threshold: 50,
      executable: false,
      validationPassed: false,
      placeable: false,
      blockReason: "Composite 62.9. Your minimum 50.0. Not auto-executable: quote 17 min old.",
    });
    expect(placement.autoSubmitOnAck).toBe(false);
    expect(placement.acknowledgeEnabled).toBe(true);
    expect(placement.placeTradeEnabled).toBe(true);
    expect(placement.overrideRequired).toBe(true);
    expect(placement.note).toContain("quote 17 min old");
    expect(placement.note).not.toContain("Auto-execute eligible");
    expect(blockedEligibilityLine(62.9, 50, "quote 17 min old")).toBe(
      "Composite 62.9. Your minimum 50.0. Not auto-executable: quote 17 min old.",
    );
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
