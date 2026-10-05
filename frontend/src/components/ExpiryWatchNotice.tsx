import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, getAccessToken } from "../api";
import { useMarketSocket } from "../hooks/useMarketSocket";
import {
  expiryNoticeStorageKey,
  shouldShowExpiryNotice,
  type ExpiryWatchResponse,
} from "../lib/expiryNotice";
import { useSession } from "../store";
import { OrderConfirmationCertificate } from "./OrderConfirmationCertificate";

function readLastShown(userId: string): string | null {
  try {
    return sessionStorage.getItem(expiryNoticeStorageKey(userId));
  } catch {
    return null;
  }
}

function writeLastShown(userId: string, marketDay: string) {
  try {
    sessionStorage.setItem(expiryNoticeStorageKey(userId), marketDay);
  } catch {
    /* private mode */
  }
}

export function ExpiryWatchNotice() {
  const qc = useQueryClient();
  const userId = useSession((s) => s.user?.id ?? "session");
  const token = getAccessToken();
  const [payload, setPayload] = useState<ExpiryWatchResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function evaluate() {
      try {
        const data = await api.expiryWatch();
        if (cancelled) return;
        const justLoggedIn = useSession.getState().expiryNoticeOnLogin;
        const show = shouldShowExpiryNotice({
          itemCount: data.items.length,
          justLoggedIn,
          marketDay: data.market_day,
          lastShownMarketDay: readLastShown(userId),
        });
        if (justLoggedIn) useSession.getState().setExpiryNoticeOnLogin(false);
        if (!show) return;
        writeLastShown(userId, data.market_day);
        setPayload(data);
        setOpen(true);
        setError("");
      } catch {
        /* leave the desk usable when the watch endpoint is down */
      }
    }

    void evaluate();
    const onVisible = () => {
      if (document.visibilityState === "visible") void evaluate();
    };
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(() => void evaluate(), 60 * 60 * 1000);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, [token, userId]);

  useMarketSocket({
    token,
    onMessage: (msg) => {
      if (msg.type !== "fill") return;
      const user = useSession.getState().user;
      if (user && msg.balance != null && msg.buying_power != null && msg.portfolio_value != null) {
        useSession.getState().setUser({
          ...user,
          cash_balance: msg.balance,
          buying_power: msg.buying_power,
          portfolio_value: msg.portfolio_value,
        });
      }
      void qc.invalidateQueries({ queryKey: ["port"] });
      void qc.invalidateQueries({ queryKey: ["pos"] });
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["pnl-history"] });
      void qc.invalidateQueries({ queryKey: ["overall-pnl"] });
      void api.expiryWatch().then((data) => {
        setPayload(data);
        if (data.items.length === 0) setOpen(false);
      }).catch(() => undefined);
    },
  });

  async function closePosition(positionId: string) {
    setClosingId(positionId);
    setError("");
    try {
      const res = await api.closePosition(positionId);
      const user = useSession.getState().user;
      if (user) {
        useSession.getState().setUser({
          ...user,
          cash_balance: res.balance,
          buying_power: res.buying_power,
          portfolio_value: res.portfolio_value,
        });
      }
      void qc.invalidateQueries({ queryKey: ["port"] });
      void qc.invalidateQueries({ queryKey: ["pos"] });
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["pnl-history"] });
      void qc.invalidateQueries({ queryKey: ["overall-pnl"] });
      const data = await api.expiryWatch();
      setPayload(data);
      if (data.items.length === 0) setOpen(false);
    } catch (ex) {
      setError((ex as Error).message);
    } finally {
      setClosingId(null);
    }
  }

  if (!token || !open || !payload || payload.items.length === 0) return null;

  return (
    <>
      <OrderConfirmationCertificate
        variant="expiry"
        details={{ items: payload.items, isPaper: payload.is_paper }}
        onDismiss={() => setOpen(false)}
        onClosePosition={(id) => void closePosition(id)}
        closingId={closingId}
      />
      {error ? (
        <p className="apex-alert apex-alert-error fixed bottom-4 left-1/2 z-[70] -translate-x-1/2" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}
