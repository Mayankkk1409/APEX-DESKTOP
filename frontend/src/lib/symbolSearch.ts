export type SymbolSearchHit = { symbol: string; name: string };

/** Under the 300 ms result budget. Cached queries skip this wait. */
export const SEARCH_DEBOUNCE_MS = 200;

const cache = new Map<string, SymbolSearchHit[]>();

export function searchCacheKey(query: string): string {
  return query.trim().toUpperCase();
}

export function clearSymbolSearchCache(): void {
  cache.clear();
}

/**
 * Debounce ticker search and reuse the last hits for the same query.
 * A cached query resolves on this turn. A new query waits `delayMs`, then
 * fetches once. A newer keystroke resolves the previous promise with null.
 */
export function createDebouncedSymbolSearch(
  fetchHits: (query: string) => Promise<{ hits: SymbolSearchHit[] }>,
  delayMs: number = SEARCH_DEBOUNCE_MS,
) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let finish: ((hits: SymbolSearchHit[] | null) => void) | undefined;

  function settle(hits: SymbolSearchHit[] | null) {
    const done = finish;
    finish = undefined;
    done?.(hits);
  }

  return {
    cancel() {
      if (timer) clearTimeout(timer);
      timer = undefined;
      settle(null);
    },
    run(query: string): Promise<SymbolSearchHit[] | null> {
      const key = searchCacheKey(query);
      const cached = cache.get(key);
      if (cached) {
        if (timer) clearTimeout(timer);
        timer = undefined;
        settle(null);
        return Promise.resolve(cached.map((hit) => ({ ...hit })));
      }
      if (timer) clearTimeout(timer);
      settle(null);
      return new Promise((resolve) => {
        finish = resolve;
        timer = setTimeout(() => {
          timer = undefined;
          const mine = finish;
          finish = undefined;
          void fetchHits(query).then(
            (result) => {
              const hits = result.hits ?? [];
              cache.set(key, hits);
              mine?.(hits);
            },
            () => {
              mine?.(null);
            },
          );
        }, delayMs);
      });
    },
  };
}
