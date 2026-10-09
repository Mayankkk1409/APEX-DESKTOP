import { useNavigate } from "react-router-dom";
import { api, setAccessToken } from "../api";
import { resetExpiryLoginArrival } from "../lib/expiryLoginNotice";
import { queryClient } from "../queryClient";
import { clearScanSession, useSession } from "../store";

export function LogoutButton() {
  const nav = useNavigate();
  const setUser = useSession((s) => s.setUser);

  async function logout() {
    try {
      await api.logout();
    } catch {
      /* clear local session even if cookie revoke fails */
    }
    queryClient.clear();
    setAccessToken(null);
    clearScanSession();
    resetExpiryLoginArrival();
    setUser(null);
    nav("/login");
  }

  return (
    <button
      type="button"
      data-testid="logout-btn"
      aria-label="Log out"
      className="shrink-0 rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-subtle hover:bg-champagne/5"
      onClick={() => void logout()}
    >
      Logout
    </button>
  );
}
