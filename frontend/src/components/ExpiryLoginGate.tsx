import { useEffect, useState } from "react";
import { api } from "../api";
import {
  expiryLoginRows,
  markExpiryLoginCertificatePainted,
  readExpiryLoginDays,
  shouldShowExpiryLoginCertificate,
  type ExpiryLoginRow,
} from "../lib/expiryLoginNotice";
import { useSession } from "../store";
import { ExpiryLoginCertificate } from "./ExpiryLoginCertificate";

/**
 * Cookie restore lands on a protected route without visiting /login.
 * The certificate is painted here before the hourly watch is allowed to run.
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
          })
        ) {
          setExpiryNoticeOnLogin(false);
          setPending(false);
          return;
        }
        if (cancelled) return;
        setExpiryNoticeOnLogin(false);
        setUserId(me.id);
        setMarketDay(watch.market_day);
        setIsPaper(watch.is_paper);
        setRows(next);
      } catch {
        if (!cancelled) setPending(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pending, setExpiryNoticeOnLogin, setPending, setUser]);

  useEffect(() => {
    if (!rows?.length || !userId || !marketDay) return;
    try {
      markExpiryLoginCertificatePainted(sessionStorage, userId, marketDay);
    } catch {
      /* private mode */
    }
    setPending(false);
  }, [rows, userId, marketDay, setPending]);

  if (!rows?.length) return null;

  return (
    <ExpiryLoginCertificate
      items={rows}
      isPaper={isPaper}
      onDismiss={() => {
        setRows(null);
      }}
    />
  );
}
