import { useEffect } from "react";
import { api } from "../api";
import { useSession } from "../store";

/**
 * Cookie restore lands on a protected route without visiting /login.
 * That is not a password or OTP login, so the expiry certificate stays down.
 * Clearing the pending flag lets the hourly watch run without painting the dialog.
 */
export function ExpiryLoginGate() {
  const pending = useSession((s) => s.expiryLoginPending);
  const setPending = useSession((s) => s.setExpiryLoginPending);
  const setUser = useSession((s) => s.setUser);
  const setExpiryNoticeOnLogin = useSession((s) => s.setExpiryNoticeOnLogin);

  useEffect(() => {
    if (!pending) return;
    let cancelled = false;
    (async () => {
      try {
        const me = (await api.me()) as import("../types").User;
        if (!cancelled) setUser(me);
      } catch {
        /* the desk can load the profile on its next request */
      } finally {
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

  return null;
}
