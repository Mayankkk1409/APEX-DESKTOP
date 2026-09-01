import { useNavigate } from "react-router-dom";
import { api, setAccessToken } from "../api";
import { useSession } from "../store";

export function LogoutButton() {
  const nav = useNavigate();
  const setUser = useSession((s) => s.setUser);

  async function logout() {
    try {
      await api.logout();
    } catch {
      /* clear local session even if cookie revoke fails */
    }
    setAccessToken(null);
    setUser(null);
    nav("/login");
  }

  return (
    <button
      type="button"
      data-testid="logout-btn"
      className="shrink-0 rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-white/70 hover:bg-white/5"
      onClick={() => void logout()}
    >
      Logout
    </button>
  );
}
