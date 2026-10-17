export type ResearchMode = "options" | "equity";

/** Gold sweep length. Options is longer so the leftward pass is as easy to follow as the rightward one. */
export const RESEARCH_WASH_MS: Record<ResearchMode, number> = {
  equity: 1600,
  options: 1900,
};

/** Fade the desk back in after the sweep has finished. */
export const RESEARCH_REVEAL_MS = 1100;

const STORAGE_KEY = "apex_research_mode";

export function readResearchMode(): ResearchMode {
  try {
    if (typeof sessionStorage === "undefined") return "options";
    return sessionStorage.getItem(STORAGE_KEY) === "equity" ? "equity" : "options";
  } catch {
    return "options";
  }
}

export function writeResearchMode(mode: ResearchMode): void {
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* private mode */
  }
}
