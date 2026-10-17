import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, getAccessToken } from "../api";
import { refreshDeskQueries } from "../lib/deskRefresh";
import { useSession } from "../store";

type ExecutionNotice = {
  id: string;
  symbol: string;
  strategy_name: string | null;
  side: string;
  qty: number;
  fill_price: number | null;
};

/**
 * After the expiry reminder closes, tell the desk about queue rows the broker has filled.
 * Dismissing the notice acknowledges it, so the same fill is not announced again.
 */
export function QueuedExecutionNotice() {
  const qc = useQueryClient();
  const token = getAccessToken();
  const expiryLoginPending = useSession((s) => s.expiryLoginPending);
  const expiryLoginCertificateOpen = useSession((s) => s.expiryLoginCertificateOpen);
  const expiryWatchOpen = useSession((s) => s.expiryWatchOpen);
  const [notices, setNotices] = useState<ExecutionNotice[] | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!token || expiryLoginPending || expiryLoginCertificateOpen || expiryWatchOpen) {
      setReady(false);
      return;
    }
    const timer = window.setTimeout(() => setReady(true), 500);
    return () => window.clearTimeout(timer);
  }, [token, expiryLoginPending, expiryLoginCertificateOpen, expiryWatchOpen]);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    void api
      .executionNotices()
      .then((data) => {
        if (!cancelled) setNotices(data.notices);
      })
      .catch(() => {
        if (!cancelled) setNotices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  useEffect(() => {
    if (!notices?.length) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void dismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function dismiss() {
    const ids = (notices ?? []).map((row) => row.id);
    setNotices([]);
    if (ids.length === 0) return;
    try {
      await api.ackExecutionNotices(ids);
    } catch {
      /* the book is already updated; a later sign-in can show the notice again */
    }
    refreshDeskQueries(qc);
  }

  if (!notices?.length) return null;
  const heading = notices.length === 1 ? "This trade has been executed." : "These trades have been executed.";

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[var(--apex-backdrop)] p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="queued-execution-title"
      data-testid="queued-execution-notice"
    >
      <div className="w-full max-w-md rounded-xl border border-line bg-panel p-5">
        <h2 id="queued-execution-title" className="font-display text-xl">
          {heading}
        </h2>
        <ul className="mt-3 space-y-2 text-sm">
          {notices.map((row) => (
            <li key={row.id} data-testid="queued-execution-row">
              <p>{row.strategy_name || row.symbol}</p>
              <p className="text-faint">
                {row.symbol} · {row.side} {row.qty}
                {row.fill_price != null ? ` · filled at ${row.fill_price.toFixed(2)}` : ""}
              </p>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="mt-4 rounded-md bg-gold px-4 py-2 text-ink"
          data-testid="queued-execution-ok"
          onClick={() => void dismiss()}
        >
          OK
        </button>
      </div>
    </div>
  );
}
