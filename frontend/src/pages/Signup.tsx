import { FormEvent, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApexLogo } from "../components/ApexLogo";
import { PasswordField } from "../components/PasswordField";
import { api } from "../api";
import { LegalFooter } from "../components/LegalFooter";
import { PAPER_PRESETS } from "../constants";
import type { AccountMode } from "../types";

export function Signup() {
  const nav = useNavigate();
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mode, setMode] = useState<AccountMode>("paper_funded");
  const [preset, setPreset] = useState<number | "custom">(100000);
  const [custom, setCustom] = useState("100000");
  const [err, setErr] = useState("");
  const [strength, setStrength] = useState({ score: 0, label: "very_weak" });

  const starting = useMemo(() => (preset === "custom" ? Number(custom) : preset), [preset, custom]);

  async function onPassword(v: string) {
    setPassword(v);
    try {
      setStrength(await api.strength(v));
    } catch {
      /* ignore */
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const body: Record<string, unknown> = {
      full_name: fullName,
      username,
      email,
      password,
      confirm_password: confirm,
      account_mode: mode,
    };
    if (mode === "paper_funded") body.starting_balance = starting;
    try {
      await api.signup(body);
      nav("/login");
    } catch (ex) {
      setErr((ex as Error).message);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10">
      <form onSubmit={onSubmit} className="w-full max-w-lg rounded-2xl border border-line bg-panel/80 p-8" data-testid="signup-form">
        <div className="mb-4 flex justify-center">
          <ApexLogo size={72} />
        </div>
        <h1 className="font-display text-2xl">Create account</h1>
        <p className="mb-6 text-xs text-bronze">
          Every account includes a paper-funded portfolio. Real brokerage (SnapTrade read-only) is connected separately.
        </p>
        <Field label="Full name" testid="full-name" value={fullName} onChange={setFullName} />
        <Field label="Username" testid="signup-username" value={username} onChange={setUsername} />
        <Field label="Email" testid="email" value={email} onChange={setEmail} />
        <PasswordField label="Password" testid="signup-password" value={password} onChange={onPassword} autoComplete="new-password" />
        <div className="mb-3 h-1.5 overflow-hidden rounded bg-ink" data-testid="strength-meter">
          <div className="h-full bg-gold transition-all" style={{ width: `${(strength.score / 5) * 100}%` }} />
        </div>
        <p className="mb-3 text-[11px] text-bronze">Strength: {strength.label}</p>
        <PasswordField label="Confirm password" testid="confirm-password" value={confirm} onChange={setConfirm} autoComplete="new-password" />

        <fieldset className="mb-4">
          <legend className="text-xs text-bronze">Account mode</legend>
          <div className="mt-2 flex gap-2">
            <Toggle active={mode === "paper_funded"} onClick={() => setMode("paper_funded")} testid="mode-paper">
              Paper Funded
            </Toggle>
            <Toggle active={mode === "real_brokerage"} onClick={() => setMode("real_brokerage")} testid="mode-real">
              Real Brokerage
            </Toggle>
          </div>
        </fieldset>

        {mode === "paper_funded" ? (
          <div data-testid="starting-balance">
            <p className="text-xs text-bronze">Starting balance</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {PAPER_PRESETS.map((p) => (
                <button
                  type="button"
                  key={p}
                  className={`rounded-md border px-3 py-1 text-sm ${preset === p ? "border-gold text-gold" : "border-line"}`}
                  onClick={() => setPreset(p)}
                >
                  ${p.toLocaleString()}
                </button>
              ))}
              <button
                type="button"
                className={`rounded-md border px-3 py-1 text-sm ${preset === "custom" ? "border-gold text-gold" : "border-line"}`}
                onClick={() => setPreset("custom")}
              >
                Custom
              </button>
            </div>
            {preset === "custom" && (
              <input
                className="mt-2 w-full rounded-md border border-line bg-ink px-3 py-2"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
              />
            )}
          </div>
        ) : null}

        {err && <p className="mt-3 text-sm text-red-400">{err}</p>}
        <button type="submit" className="mt-6 w-full rounded-md bg-gold py-2.5 font-medium text-ink" data-testid="signup-submit">
          Create account
        </button>
        <p className="mt-4 text-center text-sm text-white/50">
          Already registered?{" "}
          <Link to="/login" className="text-gold">
            Sign in
          </Link>
        </p>
        <LegalFooter className="mt-6" />
      </form>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  testid,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  testid: string;
}) {
  return (
    <label className="mb-3 block text-xs text-bronze">
      {label}
      <input
        data-testid={testid}
        type={type}
        className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-champagne"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function Toggle({
  active,
  onClick,
  children,
  testid,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
  testid: string;
}) {
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={onClick}
      className={`rounded-md border px-3 py-1.5 text-sm ${active ? "border-gold bg-gold/10 text-gold" : "border-line"}`}
    >
      {children}
    </button>
  );
}
