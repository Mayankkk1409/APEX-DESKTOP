import { Link } from "react-router-dom";

export function SettingsGearLink({ testId = "settings-link" }: { testId?: string }) {
  return (
    <Link
      to="/settings"
      className="inline-flex shrink-0 items-center justify-center rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-gold hover:bg-gold/10"
      data-testid={testId}
      aria-label="Settings"
      title="Settings"
    >
      <span aria-hidden="true">⚙</span>
    </Link>
  );
}
