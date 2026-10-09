import { displaySessionDay, formatSessionDate, markedPnl, type DailyPnlDay } from "../lib/dailyPnl";
import { fmtMoney } from "../lib/portfolioFormat";

export function DailyPnlList({ days, testId = "daily-pnl-list" }: { days: DailyPnlDay[]; testId?: string }) {
  const day = displaySessionDay(days);
  if (!day) {
    return <ul className="mt-1 flex flex-wrap gap-1.5" data-testid={testId} />;
  }
  const pnl = markedPnl(day);
  const unavailable = pnl == null;
  return (
    <ul className="mt-1 flex flex-wrap gap-1.5" data-testid={testId}>
      <li
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
