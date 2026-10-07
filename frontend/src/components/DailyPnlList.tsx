import { markedPnl, type DailyPnlDay } from "../lib/dailyPnl";
import { fmtMoney } from "../lib/portfolioFormat";

function formatSessionDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function DailyPnlList({ days, testId = "daily-pnl-list" }: { days: DailyPnlDay[]; testId?: string }) {
  return (
    <ul className="mt-1 flex flex-wrap gap-1.5" data-testid={testId}>
      {days.map((day) => {
        const pnl = markedPnl(day);
        const unavailable = pnl == null;
        return (
          <li
            key={day.date}
            data-testid={`daily-pnl-day-${day.date}`}
            data-date={day.date}
            data-status={unavailable ? "unavailable" : "marked"}
            className="rounded border border-line bg-ink/50 px-2 py-1 font-mono text-[11px] text-champagne"
          >
            <span className="text-bronze">{formatSessionDate(day.date)}</span>
            <span className={unavailable ? "text-faint" : pnl >= 0 ? "num-up" : "num-down"}>
              {" "}
              {unavailable ? "unavailable" : fmtMoney(pnl)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function PositionDailyPnl({ symbol, days }: { symbol: string; days: DailyPnlDay[] }) {
  return (
    <div data-testid="position-daily-pnl">
      <p className="text-[10px] uppercase tracking-wider text-bronze">{symbol} daily P/L</p>
      <DailyPnlList days={days} testId={`position-daily-pnl-${symbol}`} />
    </div>
  );
}
