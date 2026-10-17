/** Turn a raw calendar or news attribution into a short label and one link. */
export function presentSource(raw: string | null | undefined): { label: string; url: string | null } {
  const text = (raw || "").replace(/\s+/g, " ").trim();
  if (!text) return { label: "Source unavailable", url: null };
  const match = text.match(/https?:\/\/\S+/);
  const url = match ? match[0].replace(/[),.;]+$/, "") : null;
  let label = url ? text.slice(0, text.indexOf(url)) : text;
  label = label.replace(/\s+/g, " ").replace(/[|·,–—-]+$/, "").trim();
  if (!label && url) {
    try {
      label = new URL(url).hostname.replace(/^www\./, "");
    } catch {
      label = "Source";
    }
  }
  if (/alpaca/i.test(label)) label = "Published news";
  return { label: label || "Source", url };
}

export function earningsTiming(dte: number | null | undefined, date: string | null | undefined, fallback: string): string {
  if (typeof dte === "number" && dte < 0) {
    return date ? `Earnings passed (${date}).` : "Earnings passed.";
  }
  if (dte === 0) return date ? `Earnings today (${date}).` : "Earnings today.";
  return fallback;
}
