import { DISCLAIMER_VERBATIM, COPYRIGHT_VERBATIM, SPLASH_DURATION_MS } from "../constants";
import { ApexLogo } from "../components/ApexLogo";
import { useSession } from "../store";
import { useEffect, type CSSProperties } from "react";

export function Splash() {
  const mark = useSession((s) => s.markSplashSeen);
  const liftDelay = Math.round(SPLASH_DURATION_MS * 0.42);
  const copyDelay = Math.round(SPLASH_DURATION_MS * 0.54);
  const liftMs = Math.round(SPLASH_DURATION_MS * 0.1);
  const copyMs = Math.round(SPLASH_DURATION_MS * 0.12);

  useEffect(() => {
    const t = window.setTimeout(() => {
      mark();
    }, SPLASH_DURATION_MS);
    return () => window.clearTimeout(t);
  }, [mark]);

  return (
    <main
      className="splash-root"
      data-testid="splash"
      style={
        {
          "--splash-lift-delay": `${liftDelay}ms`,
          "--splash-lift-ms": `${liftMs}ms`,
          "--splash-copy-delay": `${copyDelay}ms`,
          "--splash-copy-ms": `${copyMs}ms`,
        } as CSSProperties
      }
    >
      <div className="splash-stage">
        <div className="splash-logo-wrap">
          <ApexLogo size={196} animate />
        </div>
        <div className="splash-fade">
          <p className="splash-wordmark">APEX</p>
          <p className="splash-tagline">Options Intelligence</p>
          <p className="splash-disclaimer" data-testid="disclaimer">
            {DISCLAIMER_VERBATIM}
          </p>
          <p className="splash-copy">{COPYRIGHT_VERBATIM}</p>
        </div>
      </div>
    </main>
  );
}
