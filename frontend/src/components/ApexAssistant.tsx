import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AssistantAskResult, AssistantEntitlement, AssistantPlan, BillingPeriod } from "../lib/assistantTypes";
import { AssistantPlansCard } from "./AssistantPlans";

const MAX_QUESTION = 2000;
const SPLASH_LOGO = "/brand/apex-splash.png";
const PANEL_EXIT_MS = 460;

type Bubble = {
  id: number;
  role: "user" | "assistant";
  text: string;
  kind?: AssistantAskResult["kind"];
  retry?: string;
};

function allowanceLine(entitlement: AssistantEntitlement | null): string {
  if (!entitlement) return "Checking your plan…";
  if (entitlement.unlimited) return `${entitlement.plan_name} · Unlimited questions a day`;
  const cap = entitlement.daily_questions ?? 0;
  return `${entitlement.plan_name} · ${entitlement.used} of ${cap} questions today`;
}

export function ApexAssistant({ startOpen = false }: { startOpen?: boolean }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [open, setOpen] = useState(startOpen);
  const [panelPresent, setPanelPresent] = useState(startOpen);
  const [panelShown, setPanelShown] = useState(startOpen);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [entitlement, setEntitlement] = useState<AssistantEntitlement | null>(null);
  const [plans, setPlans] = useState<AssistantPlan[] | null>(null);
  const [separate, setSeparate] = useState("");
  const [showPlans, setShowPlans] = useState(false);
  const [period, setPeriod] = useState<BillingPeriod>("monthly");
  const [planPos, setPlanPos] = useState<{ x: number; y: number } | null>(null);
  const [inputError, setInputError] = useState("");
  const nextId = useRef(1);

  useLayoutEffect(() => {
    if (!open) return;
    const node = panelRef.current;
    if (!node) return;
    node.getBoundingClientRect();
    const frame = requestAnimationFrame(() => setPanelShown(true));
    return () => cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (open || panelShown || !panelPresent) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setPanelPresent(false);
      return;
    }
    const timer = window.setTimeout(() => setPanelPresent(false), PANEL_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [open, panelShown, panelPresent]);

  function openChat() {
    setPanelPresent(true);
    setOpen(true);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) setPanelShown(true);
  }

  function closeChat() {
    setOpen(false);
    setPanelShown(false);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) setPanelPresent(false);
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void api.assistantEntitlement().then(
      (row) => {
        if (!cancelled) setEntitlement(row);
      },
      () => {
        if (!cancelled) setInputError("APEX AI could not read your plan. You can retry.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const node = threadRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [bubbles, pending, showPlans]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeChat();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function push(role: Bubble["role"], text: string, extra: Partial<Bubble> = {}) {
    const id = nextId.current++;
    setBubbles((current) => [...current, { id, role, text, ...extra }]);
  }

  async function togglePlans() {
    if (showPlans) {
      setShowPlans(false);
      return;
    }
    if (!plans) {
      try {
        const payload = await api.assistantPlans();
        setPlans(payload.plans);
        setSeparate(payload.separate_from_every_plan);
      } catch {
        setInputError("The plan list could not be loaded. You can retry.");
        return;
      }
    }
    setShowPlans(true);
  }

  async function ask(text: string) {
    const message = text.trim();
    if (!message || pending) return;
    if (message.length > MAX_QUESTION) {
      setInputError("Keep the question under 2,000 characters.");
      return;
    }
    setInputError("");
    setPending(true);
    push("user", message);
    setDraft("");
    try {
      const result = await api.assistantAsk(message);
      setEntitlement((current) =>
        current
          ? {
              ...current,
              used: result.used,
              daily_questions: result.daily_questions,
              unlimited: result.unlimited,
              plan_id: result.plan_id,
              plan_name: result.plan_name,
              resets_at: result.resets_at,
              reset_note: result.reset_note,
            }
          : current,
      );
      if (result.plans) {
        setPlans(result.plans);
        setSeparate(result.separate_from_every_plan ?? "");
        setShowPlans(true);
      }
      push("assistant", result.text, {
        kind: result.kind,
        retry: result.kind === "error" ? message : undefined,
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "APEX AI could not complete that request.";
      push("assistant", detail, { kind: "error", retry: message });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="apex-ai">
      {showPlans && plans ? (
        <AssistantPlansCard
          plans={plans}
          period={period}
          onPeriod={setPeriod}
          currentPlanId={entitlement?.plan_id}
          separate={separate}
          onClose={() => setShowPlans(false)}
          position={planPos}
          onPosition={setPlanPos}
        />
      ) : null}
      {panelPresent ? (
        <section
          ref={panelRef}
          id="apex-ai-panel"
          className={panelShown ? "apex-ai-panel is-open" : "apex-ai-panel"}
          role="dialog"
          aria-modal="false"
          aria-hidden={panelShown ? undefined : true}
          aria-labelledby={titleId}
          data-testid="apex-ai-panel"
        >
          <header className="apex-ai-head">
            <img src={SPLASH_LOGO} alt="" width={28} height={28} />
            <div>
              <h2 id={titleId}>APEX AI</h2>
              <p data-testid="apex-ai-allowance">{allowanceLine(entitlement)}</p>
            </div>
            <button type="button" className="apex-ai-textbtn" aria-expanded={showPlans} onClick={() => void togglePlans()}>
              View plans
            </button>
            <button type="button" className="apex-ai-close" aria-label="Close APEX AI" onClick={closeChat}>
              ×
            </button>
          </header>
          {entitlement?.reset_note ? <p className="apex-ai-status">{entitlement.reset_note}</p> : null}
          <div ref={threadRef} className="apex-ai-thread" data-testid="apex-ai-thread">
            {bubbles.map((bubble) => (
              <div key={bubble.id} className={`apex-ai-bubble is-${bubble.role}`} data-kind={bubble.kind ?? ""}>
                <p>{bubble.text}</p>
                {bubble.retry ? (
                  <button type="button" onClick={() => void ask(bubble.retry!)} disabled={pending}>
                    Retry
                  </button>
                ) : null}
              </div>
            ))}
            {pending ? <p className="apex-ai-pending">APEX AI is answering…</p> : null}
          </div>
          {inputError ? <p className="apex-ai-input-error">{inputError}</p> : null}
          <form
            className="apex-ai-compose"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(draft);
            }}
          >
            <label className="apex-ai-sr" htmlFor="apex-ai-input">
              Question for APEX AI
            </label>
            <textarea
              id="apex-ai-input"
              ref={inputRef}
              rows={2}
              maxLength={MAX_QUESTION}
              value={draft}
              disabled={pending}
              placeholder="Ask a basic question"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void ask(draft);
                }
              }}
            />
            <button type="submit" disabled={pending || draft.trim().length === 0}>
              Send
            </button>
          </form>
        </section>
      ) : null}
      <button
        type="button"
        className={open ? "apex-ai-launch is-open" : "apex-ai-launch"}
        aria-label="Open APEX AI"
        aria-expanded={open}
        aria-controls="apex-ai-panel"
        data-testid="apex-ai-launch"
        onClick={() => (open ? closeChat() : openChat())}
      >
        <img src={SPLASH_LOGO} alt="" width={36} height={36} data-testid="apex-ai-logo" />
      </button>
    </div>
  );
}
