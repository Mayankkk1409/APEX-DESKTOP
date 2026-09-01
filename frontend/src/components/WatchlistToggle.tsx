import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { WatchItem } from "../types";

export function WatchlistToggle({
  symbol,
  testid,
}: {
  symbol: string;
  testid: string;
}) {
  const qc = useQueryClient();
  const watch = useQuery({ queryKey: ["watch"], queryFn: () => api.watchlist() });
  const items = (watch.data?.items ?? []) as WatchItem[];
  const sym = symbol.trim().toUpperCase();
  const onList = items.some((w) => w.symbol.toUpperCase() === sym);

  const mutate = useMutation({
    mutationFn: async () => {
      if (!sym) return;
      if (onList) await api.removeWatch(sym);
      else await api.addWatch(sym);
    },
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["watch"] });
      const prev = qc.getQueryData<{ items: WatchItem[] }>(["watch"]);
      if (onList) {
        qc.setQueryData(["watch"], { items: (prev?.items ?? []).filter((w) => w.symbol.toUpperCase() !== sym) });
      } else {
        qc.setQueryData(["watch"], {
          items: [...(prev?.items ?? []), { symbol: sym, name: sym, price: null, change_pct: null }],
        });
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["watch"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["watch"] });
    },
  });

  return (
    <button
      type="button"
      data-testid={testid}
      disabled={!sym || mutate.isPending}
      onClick={() => mutate.mutate()}
      className="rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs text-champagne hover:border-gold/50 disabled:opacity-40"
    >
      {onList ? "Remove from watchlist" : "Add to watchlist"}
    </button>
  );
}
