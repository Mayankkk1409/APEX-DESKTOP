import type { ThemeMode } from "./theme";
import { readThemeMode, writeThemeMode } from "./theme";

export type RiskProfile = "conservative" | "moderate" | "aggressive";

export type UserSettings = {
  theme: ThemeMode;
  riskProfile: RiskProfile;
  autoExecMinScore: number;
  autoExecEnabled: boolean;
  maxRiskPerTradePct: number;
};

const STORAGE_KEY = "apex_user_settings";

export const DEFAULT_USER_SETTINGS: UserSettings = {
  theme: "dark",
  riskProfile: "moderate",
  autoExecMinScore: 85,
  autoExecEnabled: false,
  maxRiskPerTradePct: 3,
};

/** Shown under the auto-execution minimum control. */
export const AUTO_EXEC_DISCLAIMER =
  "New accounts start at the system default of 85. Auto-execution uses the minimum you set; that setting is the one that applies.";

export const RISK_PROFILE_SELECTION_NOTE =
  "This account still has Custom saved. Choose Conservative, Moderate, or Aggressive.";

export function isRiskProfile(value: unknown): value is RiskProfile {
  return value === "conservative" || value === "moderate" || value === "aggressive";
}

export function readRiskSelection(): { profile: RiskProfile | ""; selectionRequired: boolean } {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return { profile: DEFAULT_USER_SETTINGS.riskProfile, selectionRequired: false };
    const raw = (JSON.parse(stored) as { riskProfile?: unknown }).riskProfile;
    if (isRiskProfile(raw)) return { profile: raw, selectionRequired: false };
    if (raw === "custom") return { profile: "", selectionRequired: true };
  } catch {
    /* ignore */
  }
  return { profile: DEFAULT_USER_SETTINGS.riskProfile, selectionRequired: false };
}

/** The account row wins. Custom is left unresolved instead of being rewritten. */
export function selectionFromServer(value: unknown): { profile: RiskProfile | ""; selectionRequired: boolean } {
  if (isRiskProfile(value)) {
    patchUserSettings({ riskProfile: value });
    return { profile: value, selectionRequired: false };
  }
  if (value === "custom") return { profile: "", selectionRequired: true };
  if (value == null || value === "") return readRiskSelection();
  return { profile: "", selectionRequired: true };
}

function mergeSettings(raw: Partial<UserSettings> | null): UserSettings {
  const profile = isRiskProfile(raw?.riskProfile) ? raw.riskProfile : DEFAULT_USER_SETTINGS.riskProfile;
  return {
    ...DEFAULT_USER_SETTINGS,
    theme: readThemeMode(),
    ...raw,
    riskProfile: profile,
  };
}

export function readUserSettings(): UserSettings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return mergeSettings(null);
    return mergeSettings(JSON.parse(stored) as Partial<UserSettings>);
  } catch {
    return mergeSettings(null);
  }
}

export function writeUserSettings(next: UserSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  writeThemeMode(next.theme);
}

export function patchUserSettings(patch: Partial<UserSettings>): UserSettings {
  let preserveCustom = false;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    const raw = stored ? (JSON.parse(stored) as { riskProfile?: unknown }).riskProfile : null;
    preserveCustom = raw === "custom" && !Object.prototype.hasOwnProperty.call(patch, "riskProfile");
  } catch {
    preserveCustom = false;
  }
  const merged = { ...readUserSettings(), ...patch };
  if (preserveCustom) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...merged, riskProfile: "custom" }));
    } catch {
      /* ignore */
    }
    writeThemeMode(merged.theme);
  } else {
    writeUserSettings(merged);
  }
  return merged;
}
