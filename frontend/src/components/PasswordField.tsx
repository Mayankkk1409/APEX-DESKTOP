import { useState } from "react";

type PasswordFieldProps = {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testid: string;
  autoComplete?: string;
  className?: string;
};

function EyeIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M3 3l18 18" />
      <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
      <path d="M6.7 6.7C4.6 8.3 3 10.5 2 12c1.5 3 5 7 10 7 1.8 0 3.4-.5 4.8-1.3" />
      <path d="M9.9 5.1A10.7 10.7 0 0 1 12 5c5 0 8.5 4 10 7-.7 1.4-1.7 2.7-2.9 3.8" />
    </svg>
  );
}

export function PasswordField({
  label,
  value,
  onChange,
  testid,
  autoComplete,
  className = "mb-3",
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const toggleId = `${testid}-toggle`;

  return (
    <label className={`block text-xs text-bronze ${className}`}>
      {label}
      <div className="relative mt-1">
        <input
          id={testid}
          data-testid={testid}
          type={visible ? "text" : "password"}
          className="w-full rounded-md border border-line bg-ink py-2 pl-3 pr-10 text-sm text-champagne"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
        />
        <button
          type="button"
          id={toggleId}
          data-testid={`${testid}-toggle`}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-bronze hover:text-gold"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          aria-controls={testid}
        >
          <EyeIcon open={visible} />
        </button>
      </div>
    </label>
  );
}
