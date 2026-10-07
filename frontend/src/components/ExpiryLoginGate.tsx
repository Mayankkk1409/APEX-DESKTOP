import { useEffect, useState } from "react";
import { api } from "../api";
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

/**
 * Cookie restore can land on a protected route without visiting /login.
 * That arrival shows ExpiryLoginCertificate, including when no option is inside 7 days.
 * An arrival already painted on the login page does not stack a second dialog.
 */
export function ExpiryLoginGate() {
  const pending = useSession((s) => s.expiryLoginPending);
  const setPending = useSession((s) => s.setExpiryLoginPending);
  const setUser = useSession((s) => s.setUser);
  const setExpiryNoticeOnLogin = useSession((s) => s.setExpiryNoticeOnLogin);
  const [rows, setRows] = useState<ExpiryLoginRow[] | null>(null);
  const [isPaper, setIsPaper] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [marketDay, setMarketDay] = useState<string | null>(null);

  useEffect(() => {
    if (!pending) return;
    if (expiryLoginArrivalAlreadyShown()) {
      setExpiryNoticeOnLogin(false);
      setPending(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = (await api.me()) as import("../types").User;
        if (cancelled) return;
        setUser(me);
        const watch = await api.expiryWatch();
        if (cancelled) return;
        const next = expiryLoginRows(watch.items, watch.market_day);
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
        if (
          !shouldShowExpiryLoginCertificate({
            rowCount: next.length,
            marketDay: watch.market_day,
            paintedMarketDay,
            legacyNoticeDay,
            credentialLogin: false,
            alreadyPresented: expiryLoginArrivalAlreadyShown(),
          })
        ) {
          if (!cancelled) {
            setExpiryNoticeOnLogin(false);
            setPending(false);
          }
          return;
        }
        if (cancelled) return;
        markExpiryLoginArrivalShown();
        setExpiryNoticeOnLogin(false);
        setUserId(me.id);
        setMarketDay(watch.market_day);
        setIsPaper(watch.is_paper);
        setRows(next);
      } catch {
        if (!cancelled) {
          setExpiryNoticeOnLogin(false);
          setPending(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pending, setExpiryNoticeOnLogin, setPending, setUser]);

  useEffect(() => {
    if (rows === null || !userId || !marketDay) return;
    try {
      markExpiryLoginCertificatePainted(sessionStorage, userId, marketDay);
    } catch {
      /* private mode */
    }
  }, [rows, userId, marketDay]);

  if (rows !== null) {
    return (
      <ExpiryLoginCertificate
        items={rows}
        isPaper={isPaper}
        onDismiss={() => {
          setRows(null);
          setPending(false);
        }}
      />
    );
  }

  if (!pending || expiryLoginArrivalAlreadyShown()) return null;

  return <div className="order-cert-backdrop fixed inset-0 z-[60]" data-testid="expiry-login-hold" aria-hidden />;
}
