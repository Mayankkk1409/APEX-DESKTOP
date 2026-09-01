import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApexLogo } from "../components/ApexLogo";
import { PasswordField } from "../components/PasswordField";
import { OtpBoxes } from "../components/OtpBoxes";
import { LegalFooter } from "../components/LegalFooter";
import { api, AUTH_REDIRECT_KEY, setAccessToken } from "../api";
import { resolveAutofillCode } from "../lib/otpAutofill";
import { useSession } from "../store";

type Flow = "login" | "recovery";
type Stage = "identify" | "code";

export function Login() {
  const nav = useNavigate();
  const setUser = useSession((s) => s.setUser);
  const setModal = useSession((s) => s.setConnectModal);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [autofill, setAutofill] = useState<string | null>(null);
  const [otpNonce, setOtpNonce] = useState(0);
  const [otpUser, setOtpUser] = useState("");
  const [err, setErr] = useState("");
  const [flow, setFlow] = useState<Flow>("login");
  const [stage, setStage] = useState<Stage>("identify");
  const formRef = useRef<HTMLFormElement>(null);
  const flowRef = useRef<Flow>("login");
  flowRef.current = flow;

  useEffect(() => {
    const redirectMsg = sessionStorage.getItem(AUTH_REDIRECT_KEY);
    if (redirectMsg) {
      setErr(redirectMsg);
      sessionStorage.removeItem(AUTH_REDIRECT_KEY);
    }
  }, []);

  useEffect(() => {
    // Every visit to login is a new attempt — do not reuse a prior in-memory session/code.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset once per /login mount
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

  function startRecovery() {
    setErr("");
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
    setFlow("login");
    flowRef.current = "login";
    setStage("identify");
    setNewPassword("");
    setConfirmPassword("");
    setCode("");
    setAutofill(null);
    setOtpUser("");
  }

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const name = username.trim();
    try {
      await api.login(name, password);
      flowRef.current = "login";
      await beginOtpStage(name, false);
    } catch (ex) {
      setErr((ex as Error).message);
    }
  }

  async function onRequestRecoveryCode(e: FormEvent) {
    e.preventDefault();
    setErr("");
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
      setErr((ex as Error).message);
    }
  }

  async function getCode() {
    setErr("");
    try {
      await mintCode(otpUser || username.trim(), flowRef.current === "recovery");
    } catch (ex) {
      setErr((ex as Error).message);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const name = otpUser || username.trim();
    try {
      const res =
        flowRef.current === "recovery"
          ? await api.forgotPasswordVerify(name, code)
          : await api.otpVerify(name, code);
      setAccessToken(res.access_token);
      const me = (await api.me()) as import("../types").User;
      setUser(me);
      setModal(true);
      nav("/app");
    } catch (ex) {
      setErr((ex as Error).message);
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

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <form
        ref={formRef}
        onSubmit={stage === "identify" ? (isRecovery ? onRequestRecoveryCode : onLogin) : verify}
        className="w-full max-w-md rounded-2xl border border-line bg-panel/80 p-8 shadow-glow"
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
        <label className="block text-xs text-bronze">Username</label>
        <input
          data-testid="username"
          className="mt-1 mb-3 w-full rounded-md border border-line bg-ink px-3 py-2"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          readOnly={showOtp && isRecovery}
        />
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
        {showOtp && (
          <div className="mb-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-bronze">{isRecovery ? "Security code" : "One-time code"}</span>
              <button type="button" data-testid="get-code" className="text-xs text-gold underline" onClick={getCode}>
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
        <button type="submit" className="w-full rounded-md bg-gold py-2.5 font-medium text-ink" data-testid="login-submit">
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
  );
}
