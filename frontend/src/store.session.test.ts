import { afterEach, describe, expect, it, vi } from "vitest";
import { SCAN_SESSION_KEY, clearScanSession, rehydrateScanSession, useSession } from "./store";

const bag = new Map<string, string>();

function installSessionStorage() {
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => bag.get(key) ?? null,
    setItem: (key: string, value: string) => {
      bag.set(key, value);
    },
    removeItem: (key: string) => {
      bag.delete(key);
    },
  });
}

describe("scan session across re-auth", () => {
  afterEach(() => {
    bag.clear();
    clearScanSession();
    vi.unstubAllGlobals();
  });

  it("keeps symbol, expiry, bars, and the recommendation when the user is cleared", () => {
    installSessionStorage();
    const bars = [{ t: "2026-10-01T00:00:00Z", o: 1, h: 2, l: 0.5, c: 1.5, v: 10 }];
    const recommendation = {
      symbol: "AAPL",
      expiry: "2026-10-16",
      strike: 320,
      side: "put" as const,
      contract_id: null,
    };
    useSession.getState().setSymbol("AAPL");
    useSession.getState().setExpiry("2026-10-16");
    useSession.getState().setRecommendedContract(recommendation);
    useSession.getState().captureSnapshot(
      {
        symbol: "AAPL",
        timeframe: "1D",
        visible_from: "2026-01-01T00:00:00+00:00",
        visible_to: "2026-10-05T00:00:00+00:00",
        studies: ["EMA_9"],
        captured_at: "2026-10-05T00:00:00+00:00",
      },
      null,
      false,
      bars,
    );
    useSession.getState().setUser(null);

    const state = useSession.getState();
    expect(state.symbol).toBe("AAPL");
    expect(state.expiry).toBe("2026-10-16");
    expect(state.capturedBars).toEqual(bars);
    expect(state.recommendedContract).toEqual(recommendation);

    const stored = bag.get(SCAN_SESSION_KEY) ?? "";
    expect(stored).toContain("AAPL");
    expect(stored).toContain("2026-10-16");
    expect(stored).not.toContain("access_token");
    expect(stored).not.toContain("refresh_token");

    useSession.setState({
      symbol: "SPX",
      expiry: "",
      capturedBars: [],
      visibleBars: [],
      recommendedContract: null,
      snapshot: null,
    });
    // That reset rewrites sessionStorage. A document reload would still have the
    // captured scan, so put that payload back and load it the way the module does.
    bag.set(SCAN_SESSION_KEY, stored);
    rehydrateScanSession();
    expect(useSession.getState().symbol).toBe("AAPL");
    expect(useSession.getState().expiry).toBe("2026-10-16");
    expect(useSession.getState().capturedBars).toEqual(bars);
    expect(useSession.getState().recommendedContract).toEqual(recommendation);
  });
});
