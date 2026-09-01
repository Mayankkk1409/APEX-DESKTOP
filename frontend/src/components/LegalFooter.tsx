import { COPYRIGHT_VERBATIM, DISCLAIMER_VERBATIM } from "../constants";

export function LegalFooter({ className = "" }: { className?: string }) {
  return (
    <footer className={`text-center text-[10px] text-faint ${className}`}>
      <p data-testid="disclaimer">{DISCLAIMER_VERBATIM}</p>
      <p className="mt-1">{COPYRIGHT_VERBATIM}</p>
    </footer>
  );
}
