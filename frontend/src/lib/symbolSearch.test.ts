import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SEARCH_DEBOUNCE_MS,
  clearSymbolSearchCache,
  createDebouncedSymbolSearch,
} from "./symbolSearch";

afterEach(() => {
  clearSymbolSearchCache();
  vi.useRealTimers();
});

describe("debounced symbol search", () => {
  it("keeps the debounce inside the 300 ms budget", () => {
    expect(SEARCH_DEBOUNCE_MS).toBeLessThan(300);
  });

  it("collapses keystrokes to the latest query", async () => {
    vi.useFakeTimers();
    const fetchHits = vi.fn(async (query: string) => ({
      hits: [{ symbol: query.trim().toUpperCase(), name: "Name" }],
    }));
    const search = createDebouncedSymbolSearch(fetchHits, SEARCH_DEBOUNCE_MS);

    const first = search.run("m");
    const second = search.run("ms");
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);

    expect(await first).toBeNull();
    expect(await second).toEqual([{ symbol: "MS", name: "Name" }]);
    expect(fetchHits).toHaveBeenCalledTimes(1);
    expect(fetchHits).toHaveBeenCalledWith("ms");
  });

  it("returns a cached query immediately and skips another fetch", async () => {
    vi.useFakeTimers();
    const fetchHits = vi.fn(async () => ({
      hits: [{ symbol: "MS", name: "Morgan Stanley" }],
    }));
    const search = createDebouncedSymbolSearch(fetchHits, SEARCH_DEBOUNCE_MS);

    const pending = search.run("ms");
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
    expect(await pending).toEqual([{ symbol: "MS", name: "Morgan Stanley" }]);

    const started = performance.now();
    const again = await search.run("MS");
    expect(performance.now() - started).toBeLessThan(300);
    expect(again).toEqual([{ symbol: "MS", name: "Morgan Stanley" }]);
    expect(fetchHits).toHaveBeenCalledTimes(1);
  });

  it("does not cache a failed fetch", async () => {
    vi.useFakeTimers();
    const fetchHits = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ hits: [{ symbol: "V", name: "Visa Inc." }] });
    const search = createDebouncedSymbolSearch(fetchHits, SEARCH_DEBOUNCE_MS);

    const failed = search.run("v");
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
    expect(await failed).toBeNull();

    const retry = search.run("v");
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
    expect(await retry).toEqual([{ symbol: "V", name: "Visa Inc." }]);
    expect(fetchHits).toHaveBeenCalledTimes(2);
  });
});
