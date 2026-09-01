export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "apex_theme";

export function readThemeMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    /* ignore */
  }
  return "dark";
}

export function writeThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
  applyTheme(mode);
}

export function resolveEffectiveTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "light" || mode === "dark") return mode;
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/** Apply theme to document — call on load and when user changes preference. */
export function applyTheme(mode: ThemeMode): "light" | "dark" {
  const effective = resolveEffectiveTheme(mode);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = effective;
    document.documentElement.style.colorScheme = effective;
  }
  return effective;
}

/** Inline bootstrap for index.html — must stay in sync with readThemeMode/resolveEffectiveTheme. */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var m=localStorage.getItem("apex_theme");var mode=m==="light"||m==="dark"||m==="system"?m:"dark";var eff=mode==="system"?(window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"):mode;document.documentElement.dataset.theme=eff;document.documentElement.style.colorScheme=eff;}catch(e){document.documentElement.dataset.theme="dark";}})();`;
