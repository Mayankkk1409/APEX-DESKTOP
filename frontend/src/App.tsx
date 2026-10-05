import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getAccessToken } from "./api";
import { Dashboard } from "./pages/Dashboard";
import { DeepScan } from "./pages/DeepScan";
import { Login } from "./pages/Login";
import { Portfolio } from "./pages/Portfolio";
import { Settings } from "./pages/Settings";
import { Signup } from "./pages/Signup";
import { Splash } from "./pages/Splash";
import { ExpiryWatchNotice } from "./components/ExpiryWatchNotice";
import { useSession } from "./store";

/** Splash plays once on the marketing entry route; deep links skip it so /portfolio is not blocked. */
const SPLASH_ENTRY = "/";

function Guard({ children }: { children: JSX.Element }) {
  const loc = useLocation();
  if (!getAccessToken()) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return children;
}

/** Keeps the dashboard chart mounted across /app ↔ /scan so the Scan snapshot is the same widget instance. */
function AuthedDesk() {
  const loc = useLocation();
  const scan = loc.pathname === "/scan";
  return (
    <>
      <div
        className={scan ? "pointer-events-none invisible fixed inset-0 z-0 overflow-hidden" : undefined}
        aria-hidden={scan}
      >
        <Dashboard />
      </div>
      {scan ? <DeepScan /> : null}
    </>
  );
}

export default function App() {
  const loc = useLocation();
  const splashSeen = useSession((s) => s.splashSeen);
  const markSplashSeen = useSession((s) => s.markSplashSeen);

  useEffect(() => {
    if (!splashSeen && loc.pathname !== SPLASH_ENTRY) {
      markSplashSeen();
    }
  }, [loc.pathname, splashSeen, markSplashSeen]);

  // bfcache restores in-memory state; replay splash on a full reload of the entry route.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted && window.location.pathname === SPLASH_ENTRY) {
        useSession.setState({ splashSeen: false });
      }
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  if (!splashSeen && loc.pathname === SPLASH_ENTRY) {
    return <Splash />;
  }

  const showExpiryNotice =
    Boolean(getAccessToken()) && loc.pathname !== "/login" && loc.pathname !== "/signup";

  return (
    <>
      {showExpiryNotice ? <ExpiryWatchNotice /> : null}
      <Routes location={loc}>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        path="/portfolio"
        element={
          <Guard>
            <Portfolio />
          </Guard>
        }
      />
      <Route
        path="/settings"
        element={
          <Guard>
            <Settings />
          </Guard>
        }
      />
      <Route
        element={
          <Guard>
            <AuthedDesk />
          </Guard>
        }
      >
        <Route path="/app" element={<></>} />
        <Route path="/scan" element={<></>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </>
  );
}
