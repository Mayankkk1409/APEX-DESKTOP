import { describe, expect, it, beforeEach, vi } from "vitest";
import { applyTheme, readThemeMode, writeThemeMode } from "./theme";

const store: Record<string, string> = {};

describe("theme", () => {
  beforeEach(() => {
    Object.keys(store).forEach((k) => delete store[k]);
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
  });

  it("defaults to dark", () => {
    expect(readThemeMode()).toBe("dark");
  });

  it("persists theme preference", () => {
    writeThemeMode("light");
    expect(readThemeMode()).toBe("light");
  });

  it("applyTheme resolves light mode", () => {
    const eff = applyTheme("light");
    expect(eff).toBe("light");
  });

  it("applyTheme resolves dark mode", () => {
    const eff = applyTheme("dark");
    expect(eff).toBe("dark");
  });
});
