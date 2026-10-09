import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApexLogo } from "../components/ApexLogo";
import { PasswordField } from "../components/PasswordField";
import { OtpBoxes } from "../components/OtpBoxes";
import { LegalFooter } from "../components/LegalFooter";
import { ExpiryLoginCertificate } from "../components/ExpiryLoginCertificate";
import { LoginCodeDialog } from "../components/LoginCodeDialog";
import { SignupNoticeDialog } from "../components/SignupNoticeDialog";
import { api, AUTH_REDIRECT_KEY, getAccessToken, restoreSession, setAccessToken } from "../api";
import { loginFailureDialog, type LoginFailureDialog } from "../lib/apiError";
import { loginCodeNotice, type LoginCodeNotice } from "../lib/loginCode";
import {
  expiryLoginArrivalAlreadyShown,
  expiryLoginRows,
  expiryLoginShouldNavigate,
  markExpiryLoginArrivalShown,
  markExpiryLoginCertificatePainted,
  readExpiryLoginDays,
  resetExpiryLoginArrival,
  shouldShowExpiryLoginCertificate,
  type ExpiryLoginCheck,
  type ExpiryLoginRow,
} from "../lib/expiryLoginNotice";
import { resolveAutofillCode } from "../lib/otpAutofill";
import { useSession } from "../store";

type Flow = "login" | "recovery";
type Stage = "identify" | "code";

const RESTORED_SCREENS = ["/app", "/scan", "/portfolio", "/settings"];

/** After a reload, Guard sends the user to /login with the screen they were on. */
export function pathAfterSessionRestore(from: unknown): string {
  if (typeof from !== "string" || !from.startsWith("/")) return "/app";
  const path = from.split("?")[0]?.split("#")[0] ?? "";
  if (RESTORED_SCREENS.some((screen) => path === screen || path.startsWith(`${screen}/`))) return path;
  return "/app";
}

export function Login({ skipSessionRestore = false }: { skipSessionRestore?: boolean } = {}) {
  const nav = useNavigate();
  const loc = useLocation();
  const setUser = useSession((s) => s.setUser);
  const setModal = useSession((s) => s.setConnectModal);
  const setExpiryNoticeOnLogin = useSession((s) => s.setExpiryNoticeOnLogin);
  const [checkingSession, setCheckingSession] = useState(!skipSessionRestore);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [autofill, setAutofill] = useState<string | null>(null);
  const [otpNonce, setOtpNonce] = useState(0);
  const [otpUser, setOtpUser] = useState("");
  const [err, setErr] = useState("");
  const [codeNotice, setCodeNotice] = useState<LoginCodeNotice | null>(null);
  const [failure, setFailure] = useState<LoginFailureDialog | null>(null);
  const [expiryRows, setExpiryRows] = useState<ExpiryLoginRow[] | null>(null);
  const [expiryIsPaper, setExpiryIsPaper] = useState(false);
  const [expiryUserId, setExpiryUserId] = useState<string | null>(null);
  const [expiryMarketDay, setExpiryMarketDay] = useState<string | null>(null);
  const [flow, setFlow] = useState<Flow>("login");
  const [stage, setStage] = useState<Stage>("identify");
  const [submitting, setSubmitting] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const flowRef = useRef<Flow>("login");
  const afterExpiryPath = useRef("/app");
  flowRef.current = flow;

  async function maybeShowExpiry(
    me: import("../types").User,
    isCancelled: () => boolean,
    credentialLogin: boolean,
  ): Promise<ExpiryLoginCheck> {
    try {
      const watch = await api.expiryWatch();
      if (isCancelled()) return "cancelled";
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
      if (
        !shouldShowExpiryLoginCertificate({
          rowCount: rows.length,
          marketDay: watch.market_day,
          paintedMarketDay,
          legacyNoticeDay,
          credentialLogin,
          alreadyPresented: expiryLoginArrivalAlreadyShown(),
        })
      ) {
        setExpiryNoticeOnLogin(false);
        return "skip";
      }
      if (isCancelled()) return "cancelled";
      markExpiryLoginArrivalShown();
      setExpiryNoticeOnLogin(false);
      setExpiryUserId(me.id);
      setExpiryMarketDay(watch.market_day);
      setExpiryIsPaper(watch.is_paper);
      setExpiryRows(rows);
      setCheckingSession(false);
      return "show";
    } catch {
      if (isCancelled()) return "cancelled";
      setExpiryNoticeOnLogin(false);
      return "skip";
    }
  }

  useEffect(() => {
    if (expiryRows === null || !expiryUserId || !expiryMarketDay) return;
    try {
      markExpiryLoginCertificatePainted(sessionStorage, expiryUserId, expiryMarketDay);
    } catch {
      /* private mode */
    }
  }, [expiryRows, expiryUserId, expiryMarketDay]);

  useEffect(() => {
    if (skipSessionRestore) return;
    let cancelled = false;
    const from = (loc.state as { from?: unknown } | null)?.from;
    const tokenBefore = getAccessToken();
    (async () => {
      const restored = await restoreSession();
      if (cancelled) return;
      const tokenNow = getAccessToken();
      if (!restored && tokenNow && tokenNow !== tokenBefore) {
        setCheckingSession(false);
        return;
      }
      if (restored) {
        try {
          const me = (await api.me()) as import("../types").User;
          if (cancelled) return;
          setUser(me);
          afterExpiryPath.current = pathAfterSessionRestore(from);
          const expiryCheck = await maybeShowExpiry(me, () => cancelled, false);
          if (cancelled || !expiryLoginShouldNavigate(expiryCheck)) return;
          nav(afterExpiryPath.current, { replace: true });
          return;
        } catch {
          /* refresh cookie was not enough to read the profile */
        }
      }
      const redirectMsg = sessionStorage.getItem(AUTH_REDIRECT_KEY);
      if (redirectMsg) {
        setFailure(loginFailureDialog(redirectMsg));
        sessionStorage.removeItem(AUTH_REDIRECT_KEY);
      }
      // Failed refresh only. Do not clear symbol, expiry, or captured bars.
      setAccessToken(null);
      setUser(null);
      setModal(false);
      setFlow("login");
      flowRef.current = "login";
      setStage("identify");
      setPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setCode("");
      setAutofill(null);
      setOtpUser("");
      setCheckingSession(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restore once per /login mount
  }, []);

  async function mintCode(forUsername: string, recovery = false) {
    const name = forUsername.trim();
    const res = recovery
      ? await api.forgotPassword(name, newPassword, confirmPassword)
      : await api.otpRequest(name);
    const next = resolveAutofillCode(res.code);
    // Seed React state immediately so Verify never races an empty `code`.
    setCode(next);
    setAutofill(next || null);
    setOtpNonce((n) => n + 1);
  }

  async function beginOtpStage(name: string, recovery: boolean) {
    setOtpUser(name);
    await mintCode(name, recovery);
    setStage("code");
  }

  function presentLoginError(message: string) {
    const notice = loginCodeNotice(message);
    if (notice) {
      setCodeNotice(notice);
      setFailure(null);
      setErr("");
      return;
    }
    setCodeNotice(null);
    setFailure(loginFailureDialog(message));
    setErr("");
  }

  function startRecovery() {
    setErr("");
    setCodeNotice(null);
    setFailure(null);
    setFlow("recovery");
    flowRef.current = "recovery";
    setStage("identify");
    setPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setCode("");
    setAutofill(null);
    setOtpUser("");
  }

  function backToLogin() {
    setErr("");
    setCodeNotice(null);
    setFailure(null);
    setFlow("login");
    flowRef.current = "login";
    setStage("identify");
    setNewPassword("");
    setConfirmPassword("");
    setCode("");
    setAutofill(null);
    setOtpUser("");
  }

  function openCodeStep(name: string) {
    setOtpUser(name);
    setCode("");
    setAutofill(null);
    setOtpNonce((n) => n + 1);
    setStage("code");
  }

  async function enterDesk(res: { access_token: string; expires_in: number; refresh_in: number }) {
    setAccessToken(res.access_token, res.expires_in, res.refresh_in);
    const me = (await api.me()) as import("../types").User;
    setUser(me);
    setModal(true);
    afterExpiryPath.current = "/app";
    resetExpiryLoginArrival();
    const expiryCheck = await maybeShowExpiry(me, () => false, true);
    if (!expiryLoginShouldNavigate(expiryCheck)) return;
    nav("/app");
  }

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setErr("");
    setCodeNotice(null);
    setFailure(null);
    const name = username.trim();
    setSubmitting(true);
    try {
      const res = await api.login(name, password);
      if (res.otp_required === false && res.access_token && res.expires_in != null && res.refresh_in != null) {
        await enterDesk({ access_token: res.access_token, expires_in: res.expires_in, refresh_in: res.refresh_in });
        return;
      }
      flowRef.current = "login";
      openCodeStep(name);
    } catch (ex) {
      presentLoginError((ex as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function onRequestRecoveryCode(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setFailure(null);
    setCodeNotice(null);
    const name = username.trim();
    if (!name) {
      setErr("Enter your username");
      return;
    }
    if (newPassword.length < 8) {
      setErr("Password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErr("Passwords do not match");
      return;
    }
    try {
      flowRef.current = "recovery";
      await beginOtpStage(name, true);
    } catch (ex) {
      presentLoginError((ex as Error).message);
    }
  }

  async function getCode() {
    if (submitting) return;
    setErr("");
    setCodeNotice(null);
    setFailure(null);
    const name = otpUser || username.trim();
    setSubmitting(true);
    try {
      if (flowRef.current === "recovery") {
        await mintCode(name, true);
        return;
      }
      await api.resendLoginCode(name, password);
      setCode("");
      setAutofill(null);
      setOtpNonce((n) => n + 1);
    } catch (ex) {
      presentLoginError((ex as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setFailure(null);
    setCodeNotice(null);
    const name = otpUser || username.trim();
    if (submitting) return;
    setSubmitting(true);
    try {
      const res =
        flowRef.current === "recovery"
          ? await api.forgotPasswordVerify(name, code)
          : await api.otpVerify(name, code);
      await enterDesk(res);
    } catch (ex) {
      presentLoginError((ex as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const isRecovery = flow === "recovery";
  const showPassword = flow === "login" && stage === "identify";
  const showRecoveryPasswords = isRecovery && stage === "identify";
  const showOtp = stage === "code";
  const submitLabel =
    stage === "identify"
      ? isRecovery
        ? "Send security code"
        : "Continue"
      : isRecovery
        ? "Reset password"
        : "Verify code";

  const expiryDialog =
    expiryRows !== null ? (
      <ExpiryLoginCertificate
        items={expiryRows}
        isPaper={expiryIsPaper}
        onDismiss={() => {
          setExpiryRows(null);
          nav(afterExpiryPath.current);
        }}
      />
    ) : null;

  if (checkingSession && !expiryDialog) {
    return (
      <main className="min-h-screen flex items-center justify-center px-4" data-testid="session-restore">
        <p className="text-subtle">Restoring session…</p>
      </main>
    );
  }

  return (
    <>
    {expiryDialog}
    {codeNotice ? <LoginCodeDialog kind={codeNotice} onClose={() => setCodeNotice(null)} /> : null}
    {failure ? (
      <SignupNoticeDialog
        title={failure.title}
        message={failure.message}
        testId={failure.testId}
        onClose={() => setFailure(null)}
        plain
      />
    ) : null}
    <main className="min-h-screen flex items-center justify-center px-4">
      <form
        ref={formRef}
        onSubmit={stage === "identify" ? (isRecovery ? onRequestRecoveryCode : onLogin) : verify}
        className="w-full max-w-md rounded-2xl border border-line bg-panel p-8"
        data-testid="login-form"
      >
        <div className="flex justify-center">
          <ApexLogo size={72} />
        </div>
        <h1 className="mt-4 mb-6 text-center font-display text-2xl">{isRecovery ? "Recover access" : "Sign in"}</h1>
        {isRecovery && stage === "identify" && (
          <p className="mb-4 rounded-md border border-gold/30 bg-gold/10 px-3 py-2 text-center text-sm text-champagne" data-testid="recovery-notice">
            Set a new password, then verify with your security code
          </p>
        )}
        {!(showOtp && !isRecovery) && (
          <>
            <label className="block text-xs text-bronze">Username</label>
            <input
              data-testid="username"
              className="mt-1 mb-3 w-full rounded-md border border-line bg-ink px-3 py-2"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              readOnly={showOtp && isRecovery}
            />
          </>
        )}
        {showPassword && (
          <>
            <PasswordField
              label="Password"
              testid="password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              className="mb-1"
            />
            <div className="mb-4 text-right">
              <button
                type="button"
                data-testid="forgot-password-link"
                className="text-xs text-gold underline"
                onClick={startRecovery}
              >
                Forgot password?
              </button>
            </div>
          </>
        )}
        {showRecoveryPasswords && (
          <>
            <PasswordField
              label="New password"
              testid="recovery-password"
              value={newPassword}
              onChange={setNewPassword}
              autoComplete="new-password"
              className="mb-3"
            />
            <PasswordField
              label="Confirm password"
              testid="recovery-confirm-password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              className="mb-4"
            />
          </>
        )}
        {showOtp && !isRecovery && (
          <div className="mb-4">
            <p className="mb-3 text-center text-sm text-subtle" data-testid="login-code-hint">
              Enter the sign-in code emailed to the address on this account.
            </p>
            <label className="block text-center text-xs text-bronze" htmlFor="login-code">
              Sign-in code
            </label>
            <input
              id="login-code"
              data-testid="login-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              className="mt-2 w-full rounded-md border border-line bg-ink px-3 py-3 text-center font-mono text-lg tracking-[0.3em]"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            />
            <div className="mt-3 text-center">
              <button
                type="button"
                data-testid="get-code"
                className="text-xs text-subtle underline disabled:opacity-60"
                onClick={getCode}
                disabled={submitting}
              >
                Email a new code
              </button>
            </div>
          </div>
        )}
        {showOtp && isRecovery && (
          <div className="mb-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-bronze">Security code</span>
              <button
                type="button"
                data-testid="get-code"
                className="text-xs text-subtle underline disabled:opacity-60"
                onClick={getCode}
                disabled={submitting}
              >
                Get new code
              </button>
            </div>
            <OtpBoxes
              key={otpNonce}
              value={code}
              onChange={setCode}
              autofill={autofill}
              onAutofillComplete={() => formRef.current?.requestSubmit()}
            />
          </div>
        )}
        {err && <p className="mb-3 apex-alert apex-alert-error" role="alert">{err}</p>}
        <button
          type="submit"
          className="w-full rounded-md bg-gold py-2.5 font-medium text-ink disabled:opacity-60"
          data-testid="login-submit"
          disabled={submitting}
        >
          {submitLabel}
        </button>
        {isRecovery ? (
          <p className="mt-4 text-center text-sm text-subtle">
            Remember your password?{" "}
            <button type="button" className="text-gold underline" data-testid="back-to-login" onClick={backToLogin}>
              Back to sign in
            </button>
          </p>
        ) : (
          <p className="mt-4 text-center text-sm text-subtle">
            New desk?{" "}
            <Link to="/signup" className="text-gold">
              Create account
            </Link>
          </p>
        )}
        <LegalFooter className="mt-6" />
      </form>
    </main>
    </>
  );
}
