import { useState } from "react";

export type CatalystEvent = {
  id: string;
  scope: "ticker" | "market";
  kind: string;
  symbol: string | null;
  title: string;
  detail: string;
  event_date: string;
  event_time: string;
  source: string;
  as_of: string;
};

export function CatalystCalendar({
  tickerEvents,
  marketEvents,
  notes,
  symbol,
  loading,
}: {
  tickerEvents: CatalystEvent[];
  marketEvents: CatalystEvent[];
  notes?: string[];
  symbol?: string;
  asOf?: string | null;
  loading?: boolean;
}) {
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState<"ticker" | "market">("ticker");
  const rows = tab === "ticker" ? tickerEvents : marketEvents;

  return (
    <div className="vol-calendar rounded-xl border border-line bg-panel" data-testid="catalyst-calendar">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-sm"
        data-testid="catalyst-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        Catalyst / event calendar <span aria-hidden>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-line px-3 py-3">
          <div className="mb-3 flex gap-2">
            <button
              type="button"
              className={`vol-cal-tab ${tab === "ticker" ? "is-active" : ""}`}
              data-testid="catalyst-tab-ticker"
              onClick={() => setTab("ticker")}
            >
              Ticker ({tickerEvents.length})
            </button>
            <button
              type="button"
              className={`vol-cal-tab ${tab === "market" ? "is-active" : ""}`}
              data-testid="catalyst-tab-market"
              onClick={() => setTab("market")}
            >
              Market ({marketEvents.length})
            </button>
          </div>
          {loading ? (
            <p className="text-sm text-white/40">Loading live calendars…</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-white/40" data-testid="catalyst-empty">
              No live events returned for this window. Sources never invent placeholders.
            </p>
          ) : (
            <ul className="max-h-56 space-y-3 overflow-auto text-sm" data-testid="catalyst-list">
              {rows.map((e) => (
                <li key={e.id}>
                  <p className="text-champagne">
                    <span className="font-mono text-bronze">{e.event_date}</span>
                    {e.event_time ? ` · ${e.event_time}` : ""} — {e.title}
                  </p>
                  <p className="text-xs text-white/50">{e.detail}</p>
                </li>
              ))}
            </ul>
          )}
          {notes?.length ? (
            <ul className="mt-3 space-y-1 text-[10px] text-white/35">
              {notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  );
}
