export function assetLabel(assetClass: string) {
  return assetClass === "us_option" ? "Option" : "Equity";
}

export function fmtMoney(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n > 0) return `+$${abs}`;
  if (n < 0) return `-$${abs}`;
  return `$${abs}`;
}

/** Dollar amount without a leading plus sign (for balances). */
export function fmtBalance(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n < 0) return `-$${abs}`;
  return `$${abs}`;
}

export function fmtPlain(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function fmtTs(iso?: string | null) {
  if (!iso) return "—";
  const trimmed = iso.trim();
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed);
  const d = new Date(hasZone ? trimmed : `${trimmed.replace(" ", "T")}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
