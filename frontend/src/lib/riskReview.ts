/** Auto-submit score gate: the saved minimum, the global toggle, and defined-risk. */
export function autoSubmitArms(input: {
  toggleOn: boolean;
  composite: number | null | undefined;
  threshold: number;
  definedRisk: boolean;
}): boolean {
  if (!input.toggleOn || !input.definedRisk) return false;
  if (input.composite == null || !Number.isFinite(input.composite)) return false;
  if (!Number.isFinite(input.threshold)) return false;
  return input.composite >= input.threshold;
}

function formatGateScore(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

/** Neutral placement note. The saved minimum never hides the recommendation. */
export function manualConfirmationNote(score: number, minimum: number): string {
  return `Manual confirmation required (score ${formatGateScore(score)} vs. your auto-execute minimum ${formatGateScore(minimum)}).`;
}

export const AUTO_EXECUTION_OFF_NOTE = "Auto-execution is off.";

/** Shown when the displayed composite is at or above the saved minimum. */
export function autoExecEligibilityLine(score: number, minimum: number): string {
  return `Composite score ${formatGateScore(score)} · Your auto-execute minimum ${formatGateScore(minimum)} · Auto-execute eligible`;
}

export type OrderPlacement = {
  autoSubmitOnAck: boolean;
  placeTradeEnabled: boolean;
  note: string | null;
};

/**
 * The saved minimum chooses acknowledgement auto-submit versus an enabled Place Trade.
 * It does not decide whether a recommendation exists.
 */
export function orderPlacement(input: {
  toggleOn: boolean;
  composite: number | null | undefined;
  threshold: number;
  definedRisk: boolean;
  hasLegs: boolean;
}): OrderPlacement {
  if (!input.hasLegs) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, note: null };
  }
  const autoSubmitOnAck = autoSubmitArms(input);
  if (autoSubmitOnAck) {
    return { autoSubmitOnAck: true, placeTradeEnabled: false, note: null };
  }
  const below =
    input.composite != null &&
    Number.isFinite(input.composite) &&
    Number.isFinite(input.threshold) &&
    input.composite < input.threshold;
  let note: string | null = null;
  if (below && input.composite != null) {
    note = manualConfirmationNote(input.composite, input.threshold);
  } else if (!input.toggleOn) {
    note = AUTO_EXECUTION_OFF_NOTE;
  }
  return {
    autoSubmitOnAck: false,
    placeTradeEnabled: true,
    note,
  };
}
