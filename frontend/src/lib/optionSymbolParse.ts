export type ParsedOptionSymbol = {
  root: string;
  expiry: string;
  expiryDate: Date | null;
  side: "call" | "put";
  strike: number;
  occ: string;
};

const OCC_RE = /^([A-Z]{1,6})(\d{6})([CP])(\d{8})$/;

/** Parse OCC option symbol (e.g. AAPL270115C00150000). Returns null if not an options contract. */
export function parseOccSymbol(symbol: string): ParsedOptionSymbol | null {
  const raw = symbol.trim().toUpperCase().replace(/\s/g, "");
  const m = raw.match(OCC_RE);
  if (!m) return null;
  const [, root, yymmdd, cp, strikeRaw] = m;
  const yy = Number(yymmdd.slice(0, 2));
  const mm = Number(yymmdd.slice(2, 4));
  const dd = Number(yymmdd.slice(4, 6));
  const year = yy >= 70 ? 1900 + yy : 2000 + yy;
  const expiryIso = `${year}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  const expiryDate = new Date(`${expiryIso}T12:00:00Z`);
  const strike = Number(strikeRaw) / 1000;
  if (!Number.isFinite(strike)) return null;
  return {
    root,
    expiry: expiryIso,
    expiryDate: Number.isNaN(expiryDate.getTime()) ? null : expiryDate,
    side: cp === "C" ? "call" : "put",
    strike,
    occ: raw,
  };
}

/** Format expiration as "Sep 18, 2026". */
export function formatOptionExpiration(expiry: string | Date | null | undefined): string {
  if (!expiry) return "—";
  const d = expiry instanceof Date ? expiry : new Date(`${String(expiry).slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return String(expiry);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatLegSide(qty: number, side?: string): "long" | "short" {
  if (side === "sell" || side === "short") return "short";
  if (side === "buy" || side === "long") return "long";
  return qty < 0 ? "short" : "long";
}
