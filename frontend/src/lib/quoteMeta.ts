export type QuoteFeed = "indicative" | "opra" | "other";

export type QuoteMeta = {
  provider: string;
  feed: QuoteFeed;
  quotedAt: string | null;
  receivedAt: string | null;
  bid: number | null;
  ask: number | null;
  bidSize: number | null;
  askSize: number | null;
  isStale: boolean;
  staleReason: string | null;
};

export function formatQuoteMeta(meta: QuoteMeta | null | undefined): string {
  if (!meta) return "";
  const feed =
    meta.feed === "indicative" ? "Indicative" : meta.feed === "opra" ? "OPRA" : meta.provider;
  const timing =
    meta.staleReason === "last_close"
      ? "last close"
      : meta.staleReason === "delayed"
        ? "delayed"
        : meta.isStale
          ? "stale"
          : "current";
  const when = meta.quotedAt || meta.receivedAt || "";
  return [meta.provider, feed, timing, when].filter(Boolean).join(" · ");
}

export function formatEarningsDate(
  date: string | null | undefined,
  status: string | null | undefined,
): string {
  if (!date || status === "unknown") return "";
  if (status === "estimated" || date.endsWith(" est.")) {
    return date.endsWith(" est.") ? date : `${date} est.`;
  }
  return date;
}
