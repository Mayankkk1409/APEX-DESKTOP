import type { PortfolioViewMode } from "../types";

const STORAGE_KEY = "apex_portfolio_view_mode";

let viewMode: PortfolioViewMode = "paper";

function readFromStorage(): PortfolioViewMode | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored === "brokerage" || stored === "paper") return stored;
  } catch {
    /* ignore */
  }
  return null;
}

const stored = readFromStorage();
if (stored) viewMode = stored;

/** Current portfolio view mode — readable during SSR/tests where zustand snapshots are stale. */
export function readPortfolioViewMode(): PortfolioViewMode {
  return viewMode;
}

export function writePortfolioViewMode(mode: PortfolioViewMode): void {
  viewMode = mode;
  try {
    if (typeof sessionStorage !== "undefined") {
      sessionStorage.setItem(STORAGE_KEY, mode);
    }
  } catch {
    /* ignore */
  }
}
