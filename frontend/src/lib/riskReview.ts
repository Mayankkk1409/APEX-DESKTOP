import { formatCompositeDecimal } from "./scoreFormat";

/**
 * Acknowledge vs Place Trade.
 * Eligibility is the server decision: composite >= the saved minimum, executable,
 * and pre-trade validation passed. A score by itself does not arm Acknowledge.
 */
export function autoSubmitArms(input: {
  /** Ignored. Kept so callers can show the browser toggle is not a second gate. */
  toggleOn?: boolean;
  /** Scan `auto_execute_eligible` / `auto_submit_on_ack` from the shared function. */
  serverAutoSubmit?: boolean;
  /** `false` only when Settings persisted auto-execution off on the server. */
  serverAutoExecEnabled?: boolean | null;
  composite: number | null | undefined;
  threshold: number;
  definedRisk: boolean;
  /** False when the strategy slide would say the structure cannot be placed. */
  executable?: boolean;
  /** False when pre-trade validation failed. */
  validationPassed?: boolean;
}): boolean {
  if (input.serverAutoExecEnabled === false) return false;
  if (input.executable === false || input.validationPassed === false) return false;
  if (input.serverAutoSubmit !== true) return false;
  if (!input.definedRisk) return false;
  const composite = input.composite;
  if (composite == null || !Number.isFinite(composite) || !Number.isFinite(input.threshold)) return false;
  return composite >= input.threshold;
}

/** Neutral placement note. The saved minimum never hides the recommendation. */
export function manualConfirmationNote(score: number, minimum: number): string {
  return `Manual confirmation required (score ${formatCompositeDecimal(score)} vs. your auto-execute minimum ${formatCompositeDecimal(minimum)}).`;
}

export const AUTO_EXECUTION_OFF_NOTE = "Auto-execution is off.";

/** Shown when the shared decision says the trade may auto-execute. */
export function autoExecEligibilityLine(score: number, minimum: number): string {
  return `Composite ${formatCompositeDecimal(score)}. Your minimum ${formatCompositeDecimal(minimum)}. Auto-execute eligible.`;
}

/** Same sentence the server uses when the trade must not auto-execute. */
export function blockedEligibilityLine(score: number, minimum: number, reason: string): string {
  const detail = reason.replace(/\.$/, "");
  return `Composite ${formatCompositeDecimal(score)}. Your minimum ${formatCompositeDecimal(minimum)}. Not auto-executable: ${detail}.`;
}

export type OrderPlacement = {
  autoSubmitOnAck: boolean;
  placeTradeEnabled: boolean;
  acknowledgeEnabled: boolean;
  note: string | null;
};

/**
 * The shared server decision chooses acknowledgement.
 * A score at or above the minimum does not, when the structure is not executable.
 */
export function orderPlacement(input: {
  toggleOn?: boolean;
  serverAutoSubmit?: boolean;
  serverAutoExecEnabled?: boolean | null;
  composite: number | null | undefined;
  threshold: number;
  definedRisk: boolean;
  hasLegs: boolean;
  executable?: boolean;
  validationPassed?: boolean;
  placeable?: boolean;
  spreadConfirmationRequired?: boolean;
  spreadConfirmed?: boolean;
  blockReason?: string | null;
}): OrderPlacement {
  const blockedNote = input.blockReason?.trim() || null;
  if (!input.hasLegs) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, acknowledgeEnabled: false, note: blockedNote };
  }
  if (input.placeable === false) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, acknowledgeEnabled: false, note: blockedNote };
  }
  if (input.executable === false && !input.spreadConfirmationRequired) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, acknowledgeEnabled: false, note: blockedNote };
  }
  if (input.validationPassed === false && !input.spreadConfirmationRequired) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, acknowledgeEnabled: false, note: blockedNote };
  }
  if (input.spreadConfirmationRequired && !input.spreadConfirmed) {
    return { autoSubmitOnAck: false, placeTradeEnabled: false, acknowledgeEnabled: false, note: blockedNote };
  }
  const autoSubmitOnAck = autoSubmitArms(input);
  if (autoSubmitOnAck) {
    return { autoSubmitOnAck: true, placeTradeEnabled: false, acknowledgeEnabled: true, note: null };
  }
  const below =
    input.composite != null &&
    Number.isFinite(input.composite) &&
    Number.isFinite(input.threshold) &&
    input.composite < input.threshold;
  let note: string | null = blockedNote;
  if (input.serverAutoExecEnabled === false) {
    note = AUTO_EXECUTION_OFF_NOTE;
  } else if (!note && below && input.composite != null) {
    note = manualConfirmationNote(input.composite, input.threshold);
  }
  return {
    autoSubmitOnAck: false,
    placeTradeEnabled: true,
    acknowledgeEnabled: false,
    note,
  };
}
