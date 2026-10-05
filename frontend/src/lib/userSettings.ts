import type { ThemeMode } from "./theme";
import { readThemeMode, writeThemeMode } from "./theme";

export type RiskProfile = "conservative" | "moderate" | "aggressive" | "custom";

export type UserSettings = {
  theme: ThemeMode;
  riskProfile: RiskProfile;
  autoExecMinScore: number;
  autoExecEnabled: boolean;
  maxRiskPerTradePct: number;
  maxPositions: number;
};

const STORAGE_KEY = "apex_user_settings";

export const DEFAULT_USER_SETTINGS: UserSettings = {
  theme: "dark",
  riskProfile: "moderate",
  autoExecMinScore: 85,
  autoExecEnabled: false,
  maxRiskPerTradePct: 3,
  maxPositions: 8,
};

/** Shown under the auto-execution minimum control. */
export const AUTO_EXEC_DISCLAIMER =
  "New accounts start at the system default of 85. Auto-execution uses the minimum you set; that setting is the one that applies.";

export function isRiskProfile(value: unknown): value is RiskProfile {
  return value === "conservative" || value === "moderate" || value === "aggressive" || value === "custom";
}

function mergeSettings(raw: Partial<UserSettings> | null): UserSettings {
  return {
    ...DEFAULT_USER_SETTINGS,
    theme: readThemeMode(),
    ...raw,
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
  const merged = { ...readUserSettings(), ...patch };
  writeUserSettings(merged);
  return merged;
}
