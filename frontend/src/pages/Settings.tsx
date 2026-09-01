import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ApexLogo } from "../components/ApexLogo";
import { BrokerageConnectionPanel } from "../components/BrokerageConnectionPanel";
import { LegalFooter } from "../components/LegalFooter";
import { LogoutButton } from "../components/LogoutButton";
import { SettingsGearLink } from "../components/SettingsGearLink";
import { useBrokerage } from "../hooks/useBrokerage";
import { formatOrderAccountLabel } from "../lib/orderFormat";
import {
  AUTO_EXEC_WARNING_THRESHOLD,
  DEFAULT_USER_SETTINGS,
  patchUserSettings,
  readUserSettings,
  type RiskProfile,
  type UserSettings,
} from "../lib/userSettings";
import { applyTheme, type ThemeMode, writeThemeMode } from "../lib/theme";
import { useSession } from "../store";

function Section({ title, children, testId }: { title: string; children: React.ReactNode; testId: string }) {
  return (
    <section className="rounded-xl border border-line bg-panel p-4" data-testid={testId}>
      <h2 className="font-display text-lg text-gold">{title}</h2>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const { user, setUser } = useSession();
  const brokerage = useBrokerage();
  const portfolio = useQuery({
    queryKey: ["port"],
    queryFn: () => api.portfolio(),
    enabled: !brokerage.usingBrokerage,
  });

  const [settings, setSettings] = useState<UserSettings>(() => readUserSettings());
  const [balanceDraft, setBalanceDraft] = useState("");
  const [balanceModalOpen, setBalanceModalOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    applyTheme(settings.theme);
  }, [settings.theme]);

  const stats = brokerage.usingBrokerage && brokerage.stats
    ? {
        cash: brokerage.stats.balance,
        buying_power: brokerage.stats.buying_power,
        equity: brokerage.stats.portfolio_value,
        day_pl: brokerage.stats.day_pnl,
      }
    : {
        cash: portfolio.data?.balance ?? user?.cash_balance ?? 0,
        buying_power: portfolio.data?.buying_power ?? user?.buying_power ?? 0,
        equity: portfolio.data?.portfolio_value ?? user?.portfolio_value ?? 0,
        day_pl: portfolio.data?.day_pl ?? null,
      };

  const starting = portfolio.data?.starting_balance ?? user?.starting_balance ?? stats.equity;
  const totalPl = stats.equity - (starting || stats.equity);

  function persist(patch: Partial<UserSettings>) {
    const next = patchUserSettings({ ...settings, ...patch });
    setSettings(next);
    void api.syncSettings(next).catch(() => undefined);
  }

  const resetBalance = useMutation({
    mutationFn: (amount: number) => api.resetPaperBalance(amount),
    onSuccess: (u) => {
      setUser(u);
      setBalanceModalOpen(false);
      setBalanceDraft("");
      setStatusMsg("Paper balance updated (simulation only).");
      void qc.invalidateQueries({ queryKey: ["port"] });
      void qc.invalidateQueries({ queryKey: ["pnl-history"] });
    },
    onError: (e) => setStatusMsg((e as Error).message),
  });

  const deleteAccount = useMutation({
    mutationFn: () => api.deleteAccount(deletePassword || undefined),
    onSuccess: () => {
      window.location.assign("/login");
    },
    onError: (e) => setStatusMsg((e as Error).message),
  });

  const lowAutoExec = settings.autoExecMinScore < AUTO_EXEC_WARNING_THRESHOLD;

  return (
    <div className="min-h-screen" data-testid="settings-page">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <ApexLogo size={36} className="shrink-0" />
          <p className="font-display text-xl tracking-[0.2em]">APEX</p>
          <Link to="/app" className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-gold hover:bg-gold/10">
            Dashboard
          </Link>
          <Link to="/portfolio" className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-gold hover:bg-gold/10">
            Portfolio
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <SettingsGearLink />
          <LogoutButton />
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
        <div>
          <h1 className="font-display text-2xl">Settings</h1>
          <p className="mt-1 text-sm text-subtle">Account, connections, risk controls, and appearance.</p>
        </div>

        {statusMsg && (
          <p className="rounded-md border border-line bg-panel px-3 py-2 text-sm text-champagne" role="status">
            {statusMsg}
          </p>
        )}

        <Section title="Account" testId="settings-account">
          {!brokerage.usingBrokerage && (
            <p className="text-xs text-faint" data-testid="settings-paper-audit">
              Paper trading only — balance changes affect your simulation account, not real funds.
            </p>
          )}
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-subtle">Cash</dt>
              <dd className="font-mono" data-testid="settings-cash">
                ${stats.cash.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </dd>
            </div>
            <div>
              <dt className="text-subtle">Buying power</dt>
              <dd className="font-mono" data-testid="settings-bp">
                ${stats.buying_power.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </dd>
            </div>
            <div>
              <dt className="text-subtle">Equity</dt>
              <dd className="font-mono" data-testid="settings-equity">
                ${stats.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </dd>
            </div>
            <div>
              <dt className="text-subtle">Total P&amp;L</dt>
              <dd className={`font-mono ${totalPl >= 0 ? "num-up" : "num-down"}`} data-testid="settings-pnl">
                {totalPl >= 0 ? "+" : ""}
                {totalPl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </dd>
            </div>
          </dl>
          {!brokerage.usingBrokerage && (
            <button
              type="button"
              className="rounded-md border border-line px-3 py-2 text-sm text-gold hover:bg-gold/10"
              data-testid="settings-edit-balance"
              onClick={() => {
                setBalanceDraft(String(Math.round(stats.equity)));
                setBalanceModalOpen(true);
              }}
            >
              Edit / reset paper balance
            </button>
          )}
        </Section>

        <Section title="Brokerage connections" testId="settings-brokerage">
          <p className="text-xs text-faint">Connected accounts are read-only — APEX cannot place live trades.</p>
          <BrokerageConnectionPanel />
        </Section>

        <Section title="Risk &amp; auto-execution" testId="settings-risk">
          <label className="block text-sm">
            <span className="text-subtle">Risk profile</span>
            <select
              className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm"
              data-testid="settings-risk-profile"
              value={settings.riskProfile}
              onChange={(e) => persist({ riskProfile: e.target.value as RiskProfile })}
            >
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="aggressive">Aggressive</option>
              <option value="custom">Custom</option>
            </select>
          </label>

          <label className="block text-sm">
            <span className="text-subtle">
              Auto-execution minimum score: <strong data-testid="settings-auto-exec-value">{settings.autoExecMinScore}</strong>
            </span>
            <input
              type="range"
              min={0}
              max={100}
              className="mt-2 w-full accent-gold"
              data-testid="settings-auto-exec-slider"
              value={settings.autoExecMinScore}
              onChange={(e) => persist({ autoExecMinScore: Number(e.target.value) })}
            />
          </label>
          {lowAutoExec && (
            <p className="apex-alert apex-alert-warn" data-testid="settings-auto-exec-warning" role="alert">
              Scores below 72 increase false-positive risk — auto-execution is not recommended.
            </p>
          )}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              data-testid="settings-auto-exec-toggle"
              checked={settings.autoExecEnabled}
              onChange={(e) => persist({ autoExecEnabled: e.target.checked })}
            />
            <span>Global auto-execution (off by default)</span>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="text-subtle">Max risk per trade (%)</span>
              <input
                type="number"
                min={0.5}
                max={10}
                step={0.5}
                className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2"
                data-testid="settings-max-risk"
                value={settings.maxRiskPerTradePct}
                onChange={(e) => persist({ maxRiskPerTradePct: Number(e.target.value) })}
              />
            </label>
            <label className="block text-sm">
              <span className="text-subtle">Max open positions</span>
              <input
                type="number"
                min={1}
                max={50}
                className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2"
                data-testid="settings-max-positions"
                value={settings.maxPositions}
                onChange={(e) => persist({ maxPositions: Number(e.target.value) })}
              />
            </label>
          </div>
        </Section>

        <Section title="Appearance" testId="settings-appearance">
          <fieldset className="flex flex-wrap gap-3">
            {(["light", "dark", "system"] as ThemeMode[]).map((mode) => (
              <label key={mode} className="flex cursor-pointer items-center gap-2 text-sm capitalize">
                <input
                  type="radio"
                  name="theme"
                  data-testid={`settings-theme-${mode}`}
                  checked={settings.theme === mode}
                  onChange={() => {
                    writeThemeMode(mode);
                    persist({ theme: mode });
                  }}
                />
                {mode}
              </label>
            ))}
          </fieldset>
        </Section>

        <Section title="Security" testId="settings-security">
          <p className="text-sm text-subtle">Signed in as {user?.username ?? "—"} · {formatOrderAccountLabel(user)}</p>
          <LogoutButton />
          <button
            type="button"
            className="apex-btn-danger-outline"
            data-testid="settings-delete-account"
            onClick={() => setDeleteOpen(true)}
          >
            Delete account
          </button>
        </Section>
      </main>

      <LegalFooter className="px-4 pb-6" />

      {balanceModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--apex-backdrop)]" data-testid="settings-balance-modal">
          <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6" role="dialog" aria-modal="true">
            <h3 className="font-display text-xl">Reset paper balance?</h3>
            <p className="mt-2 text-sm text-subtle">
              Simulation only — this adjusts your paper starting balance and clears open paper positions when the backend supports it.
            </p>
            <input
              type="number"
              min={1000}
              className="mt-4 w-full rounded-md border border-line bg-panel px-3 py-2"
              data-testid="settings-balance-input"
              value={balanceDraft}
              onChange={(e) => setBalanceDraft(e.target.value)}
            />
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                className="flex-1 rounded-md bg-gold py-2 text-ink disabled:opacity-40"
                data-testid="settings-balance-confirm"
                disabled={resetBalance.isPending || Number(balanceDraft) < 1000}
                onClick={() => resetBalance.mutate(Number(balanceDraft))}
              >
                Confirm reset
              </button>
              <button type="button" className="flex-1 rounded-md border border-line py-2" onClick={() => setBalanceModalOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--apex-backdrop)]" data-testid="settings-delete-modal">
          <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6" role="dialog" aria-modal="true">
            <h3 className="font-display text-xl text-[var(--apex-error-text)]">Delete account permanently?</h3>
            <p className="mt-2 text-sm text-subtle">Type DELETE to confirm. This cannot be undone.</p>
            <input
              className="mt-4 w-full rounded-md border border-line bg-panel px-3 py-2"
              placeholder="DELETE"
              data-testid="settings-delete-confirm-input"
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
            />
            <input
              type="password"
              className="mt-2 w-full rounded-md border border-line bg-panel px-3 py-2"
              placeholder="Password (if required)"
              data-testid="settings-delete-password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
            />
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                className="apex-btn-danger flex-1 disabled:opacity-40"
                data-testid="settings-delete-confirm"
                disabled={deleteConfirm !== "DELETE" || deleteAccount.isPending}
                onClick={() => deleteAccount.mutate()}
              >
                Delete my account
              </button>
              <button type="button" className="flex-1 rounded-md border border-line py-2" onClick={() => setDeleteOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export { DEFAULT_USER_SETTINGS };
