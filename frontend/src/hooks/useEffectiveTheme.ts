import { useSyncExternalStore } from "react";

function getTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribe(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => obs.disconnect();
}

/** Re-render when `html[data-theme]` changes (light / dark bootstrap + Settings). */
export function useEffectiveTheme(): "light" | "dark" {
  return useSyncExternalStore(subscribe, getTheme, () => "dark");
}
