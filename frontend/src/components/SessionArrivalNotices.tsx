import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, getAccessToken } from "../api";
import { refreshDeskQueries } from "../lib/deskRefresh";
import {
  expiryLoginArrivalAlreadyShown,
  expiryLoginRows,
  markExpiryLoginArrivalShown,
  markExpiryLoginCertificatePainted,
  readExpiryLoginDays,
  shouldShowExpiryLoginCertificate,
  type ExpiryLoginRow,
} from "../lib/expiryLoginNotice";
import { useSession } from "../store";
import { ExpiryLoginCertificate } from "./ExpiryLoginCertificate";

type CloseNotice = {
  id: string;
  symbol: string;
  side: string;
  qty: number;
  fill_price: number | null;
  basis?: number | null;
};

type ExecNotice = {
  id: string;
  symbol: string;
  strategy_name: string | null;
  side: string;
  qty: number;
  fill_price: number | null;
};

type Step = "loading" | "closed" | "executed" | "expiry" | "done";

/**
 * Sign-in order: legs closed today → trades executed from pending → expiry reminder.
 * Money on the desk is refreshed after each dismiss so cash and P&L match the book.
 */
export function SessionArrivalNotices({ otpEntry = false }: { otpEntry?: boolean }) {
  const qc = useQueryClient();
  const token = getAccessToken();
  const pending = useSession((s) => s.expiryLoginPending);
  const setPending = useSession((s) => s.setExpiryLoginPending);
  const setUser = useSession((s) => s.setUser);
  const setExpiryNoticeOnLogin = useSession((s) => s.setExpiryNoticeOnLogin);
  const setExpiryLoginCertificateOpen = useSession((s) => s.setExpiryLoginCertificateOpen);
  const [step, setStep] = useState<Step>("loading");
  const [closed, setClosed] = useState<CloseNotice[]>([]);
  const [executed, setExecuted] = useState<ExecNotice[]>([]);
  const [expiryRows, setExpiryRows] = useState<ExpiryLoginRow[] | null>(null);
  const [expiryPaper, setExpiryPaper] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [marketDay, setMarketDay] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !pending) return;
    if (expiryLoginArrivalAlreadyShown() && !otpEntry) {
      setExpiryNoticeOnLogin(false);
      setPending(false);
      setStep("done");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = (await api.me()) as import("../types").User;
        if (cancelled) return;
        setUser(me);
        setUserId(me.id);
        const [bundle, watch] = await Promise.all([api.sessionNotices(), api.expiryWatch()]);
        if (cancelled) return;
        setMarketDay(bundle.market_day || watch.market_day);
        setClosed(bundle.closed_today || []);
        setExecuted(bundle.executed_today || []);
        const rows = expiryLoginRows(watch.items, watch.market_day);
        let paintedMarketDay: string | null = null;
        let legacyNoticeDay: string | null = null;
        try {
          const days = readExpiryLoginDays(sessionStorage, me.id);
          paintedMarketDay = days.paintedMarketDay;
          legacyNoticeDay = days.legacyNoticeDay;
        } catch {
          paintedMarketDay = null;
          legacyNoticeDay = null;
        }
        const showExpiry = shouldShowExpiryLoginCertificate({
          rowCount: rows.length,
          marketDay: watch.market_day,
          paintedMarketDay,
          legacyNoticeDay,
          credentialLogin: otpEntry,
          alreadyPresented: expiryLoginArrivalAlreadyShown(),
          otpEntry,
        });
        setExpiryPaper(watch.is_paper);
        setExpiryRows(showExpiry ? rows : null);
        markExpiryLoginArrivalShown();
        setExpiryNoticeOnLogin(false);
        if ((bundle.closed_today || []).length) setStep("closed");
        else if ((bundle.executed_today || []).length) setStep("executed");
        else if (showExpiry) setStep("expiry");
        else {
          setPending(false);
          setStep("done");
        }
      } catch {
        if (!cancelled) {
          setExpiryNoticeOnLogin(false);
          setPending(false);
          setStep("done");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, pending, otpEntry, setExpiryNoticeOnLogin, setPending, setUser]);

  useEffect(() => {
    setExpiryLoginCertificateOpen(step === "expiry");
    return () => setExpiryLoginCertificateOpen(false);
  }, [step, setExpiryLoginCertificateOpen]);

  useEffect(() => {
    if (step !== "expiry" || !userId || !marketDay) return;
    try {
      markExpiryLoginCertificatePainted(sessionStorage, userId, marketDay);
    } catch {
      /* private mode */
    }
  }, [step, userId, marketDay]);

  async function finishClosed() {
    const ids = closed.map((row) => row.id);
    setClosed([]);
    if (ids.length) {
      try {
        await api.ackClosedSessionNotices(ids);
      } catch {
        /* book already closed */
      }
    }
    refreshDeskQueries(qc);
    if (executed.length) setStep("executed");
    else if (expiryRows !== null) setStep("expiry");
    else {
      setPending(false);
      setStep("done");
    }
  }

  async function finishExecuted() {
    const ids = executed.map((row) => row.id);
    setExecuted([]);
    if (ids.length) {
      try {
        await api.ackExecutionNotices(ids);
      } catch {
        /* already booked */
      }
    }
    refreshDeskQueries(qc);
    try {
      const me = (await api.me()) as import("../types").User;
      setUser(me);
    } catch {
      /* desk queries still refresh balances */
    }
    if (expiryRows !== null) setStep("expiry");
    else {
      setPending(false);
      setStep("done");
    }
  }

  function finishExpiry() {
    setExpiryRows(null);
    setPending(false);
    setStep("done");
    refreshDeskQueries(qc);
  }

  if (!pending || step === "loading" || step === "done") return null;

  if (step === "closed" && closed.length) {
    const heading = closed.length === 1 ? "This position was closed today." : "These positions were closed today.";
    return (
      <div
        className="fixed inset-0 z-[80] flex items-center justify-center bg-[var(--apex-backdrop)] p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="closed-today-title"
        data-testid="closed-today-notice"
      >
        <div className="w-full max-w-md rounded-xl border border-line bg-panel p-5">
          <h2 id="closed-today-title" className="font-display text-xl">
            {heading}
          </h2>
          <ul className="mt-3 space-y-2 text-sm">
            {closed.map((row) => (
              <li key={row.id} data-testid="closed-today-row">
                <p>{row.symbol}</p>
                <p className="text-faint">
                  {row.side} {row.qty}
                  {row.fill_price != null ? ` · closed at ${Number(row.fill_price).toFixed(2)}` : ""}
                </p>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="mt-4 rounded-md bg-gold px-4 py-2 text-ink"
            data-testid="closed-today-ok"
            onClick={() => void finishClosed()}
          >
            OK
          </button>
        </div>
      </div>
    );
  }

  if (step === "executed" && executed.length) {
    const heading = executed.length === 1 ? "This trade has been executed." : "These trades have been executed.";
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
            {executed.map((row) => (
              <li key={row.id} data-testid="queued-execution-row">
                <p>{row.strategy_name || row.symbol}</p>
                <p className="text-faint">
                  {row.symbol} · {row.side} {row.qty}
                  {row.fill_price != null ? ` · filled at ${Number(row.fill_price).toFixed(2)}` : ""}
                </p>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="mt-4 rounded-md bg-gold px-4 py-2 text-ink"
            data-testid="queued-execution-ok"
            onClick={() => void finishExecuted()}
          >
            OK
          </button>
        </div>
      </div>
    );
  }

  if (step === "expiry" && expiryRows !== null) {
    return <ExpiryLoginCertificate items={expiryRows} isPaper={expiryPaper} onDismiss={finishExpiry} />;
  }

  return null;
}
