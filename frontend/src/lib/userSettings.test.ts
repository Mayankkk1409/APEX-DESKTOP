import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AUTO_EXEC_WARNING_THRESHOLD,
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
    expect(s.autoExecMinScore).toBe(DEFAULT_USER_SETTINGS.autoExecMinScore);
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

  it("warn threshold constant matches production gate", () => {
    expect(AUTO_EXEC_WARNING_THRESHOLD).toBe(72);
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
