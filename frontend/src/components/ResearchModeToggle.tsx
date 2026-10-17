import { readResearchMode, writeResearchMode, type ResearchMode } from "../lib/researchMode";
import { useSession } from "../store";

/** Switches the research workflow. It does not change the account, balances, or send an order. */
export function ResearchModeToggle({ testId = "research-mode" }: { testId?: string }) {
  const mode = useSession((s) => s.researchMode);
  const setMode = useSession((s) => s.setResearchMode);
  const current = mode || readResearchMode();

  function choose(next: ResearchMode) {
    if (next === current) return;
    writeResearchMode(next);
    setMode(next);
  }

  return (
    <div className="research-mode" role="group" aria-label="Research mode" data-testid={testId} data-mode={current}>
      <span className={`research-mode-thumb${current === "equity" ? " is-equity" : ""}`} aria-hidden="true" />
      {(["options", "equity"] as const).map((choice) => (
        <button
          key={choice}
          type="button"
          aria-pressed={current === choice}
          data-testid={`${testId}-${choice}`}
          className={current === choice ? "is-selected" : ""}
          onClick={() => choose(choice)}
        >
          {choice === "options" ? "Options" : "Equity"}
        </button>
      ))}
    </div>
  );
}
