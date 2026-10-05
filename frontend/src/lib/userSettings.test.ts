import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AUTO_EXEC_DISCLAIMER,
  DEFAULT_USER_SETTINGS,
  patchUserSettings,
  readUserSettings,
  writeUserSettings,
} from "./userSettings";
import { readThemeMode, writeThemeMode } from "./theme";

const store: Record<string, string> = {};

function stubStorage() {
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {
      Object.keys(store).forEach((k) => delete store[k]);
    },
  });
  vi.stubGlobal("document", {
    documentElement: {
      dataset: {} as DOMStringMap,
      style: {} as CSSStyleDeclaration,
      removeAttribute: () => undefined,
    },
  });
}

describe("userSettings", () => {
  beforeEach(() => {
    Object.keys(store).forEach((k) => delete store[k]);
    stubStorage();
    vi.restoreAllMocks();
    stubStorage();
  });

  it("returns defaults when storage is empty", () => {
    const s = readUserSettings();
    expect(DEFAULT_USER_SETTINGS.autoExecMinScore).toBe(85);
    expect(s.autoExecMinScore).toBe(85);
    expect(s.autoExecEnabled).toBe(false);
    expect(s.maxRiskPerTradePct).toBe(3);
  });

  it("persists patched settings to localStorage", () => {
    const next = patchUserSettings({ autoExecMinScore: 78, riskProfile: "aggressive" });
    expect(next.autoExecMinScore).toBe(78);
    expect(next.riskProfile).toBe("aggressive");
    const stored = JSON.parse(store["apex_user_settings"] ?? "{}");
    expect(stored.autoExecMinScore).toBe(78);
  });

  it("syncs theme when writing settings", () => {
    writeUserSettings({ ...DEFAULT_USER_SETTINGS, theme: "light" });
    expect(readThemeMode()).toBe("light");
  });

  it("disclaimer states the new-account default and that the saved minimum applies", () => {
    expect(AUTO_EXEC_DISCLAIMER).toBe(
      "New accounts start at the system default of 85. Auto-execution uses the minimum you set; that setting is the one that applies.",
    );
    expect(AUTO_EXEC_DISCLAIMER).not.toContain("Scores below 72 increase false-positive risk");
    expect(AUTO_EXEC_DISCLAIMER).not.toContain("below 72");
    expect(AUTO_EXEC_DISCLAIMER).not.toContain("BELOW EXECUTION THRESHOLD");
  });
});

describe("userSettings theme integration", () => {
  beforeEach(() => {
    Object.keys(store).forEach((k) => delete store[k]);
    stubStorage();
  });

  it("applies dark theme by default", () => {
    writeThemeMode("dark");
    expect(readThemeMode()).toBe("dark");
  });

  it("persists theme preference", () => {
    writeThemeMode("light");
    expect(readThemeMode()).toBe("light");
  });
});
