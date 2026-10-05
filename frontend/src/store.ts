import { create } from "zustand";
import type { OhlcBar } from "./lib/ta";
import { readPortfolioViewMode, writePortfolioViewMode } from "./lib/portfolioViewMode";
import type { AccountMode, ChartSnapshot, PortfolioViewMode, RecommendedContract, User } from "./types";

/** Scan progress only. Never put access or refresh tokens here. */
export const SCAN_SESSION_KEY = "apex_scan_session";

type PersistedScan = {
  symbol: string;
  timeframe: string;
  expiry: string;
  recommendedContract: RecommendedContract | null;
  snapshot: ChartSnapshot | null;
  capturedBars: OhlcBar[];
  capturedContext: OhlcBar[];
  capturedDaily: OhlcBar[];
};

function browserSessionStorage(): Storage | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    return sessionStorage;
  } catch {
    return null;
  }
}

function readPersistedScan(): Partial<PersistedScan> {
  const store = browserSessionStorage();
  if (!store) return {};
  try {
    const raw = store.getItem(SCAN_SESSION_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<PersistedScan>;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return parsed;
  } catch {
    return {};
  }
}

function writePersistedScan(state: {
  symbol: string;
  timeframe: string;
  expiry: string;
  recommendedContract: RecommendedContract | null;
  snapshot: ChartSnapshot | null;
  capturedBars: OhlcBar[];
  capturedContext: OhlcBar[];
  capturedDaily: OhlcBar[];
}) {
  const store = browserSessionStorage();
  if (!store) return;
  const payload: PersistedScan = {
    symbol: state.symbol,
    timeframe: state.timeframe,
    expiry: state.expiry,
    recommendedContract: state.recommendedContract,
    snapshot: state.snapshot,
    capturedBars: state.capturedBars,
    capturedContext: state.capturedContext,
    capturedDaily: state.capturedDaily,
  };
  store.setItem(SCAN_SESSION_KEY, JSON.stringify(payload));
}

const persistedScan = readPersistedScan();

/**
 * Scan session fields sibling Deep Scan layers read:
 *   symbol, timeframe, expiry, snapshot, capturedBars (alias visibleBars),
 *   capturedContext, capturedDaily, chartImage, recommendedContract
 */
interface SessionState {
  splashSeen: boolean;
  user: User | null;
  accountMode: AccountMode | null;
  /** Selected SnapTrade account — shared across dashboard, portfolio, and brokerage panel. */
  selectedBrokerageAccountId: string | null;
  /** Paper vs connected brokerage — controls which data feeds dashboard/portfolio. */
  portfolioViewMode: PortfolioViewMode;
  showConnectModal: boolean;
  /** Set on a fresh sign-in so the expiry notice shows even if this market day was already seen. */
  expiryNoticeOnLogin: boolean;
  symbol: string;
  timeframe: string;
  /** Dashboard-selected option expiry — persisted for the whole scan session. */
  expiry: string;
  /** Single contract the §5 strategy scoring engine recommends for this scan session. */
  recommendedContract: RecommendedContract | null;
  snapshot: ChartSnapshot | null;
  chartImage: string | null;
  chartImageFrozen: boolean;
  /** Bars inside the visible range at Scan click — the only TA analysis input. */
  capturedBars: OhlcBar[];
  /** Alias for capturedBars — sibling layers may read either name. */
  visibleBars: OhlcBar[];
  /** Full loaded series, so EMA 200 etc. warm up before the captured window. */
  capturedContext: OhlcBar[];
  /** Daily series backing daily-based pivot values. */
  capturedDaily: OhlcBar[];
  markSplashSeen: () => void;
  setUser: (user: User | null) => void;
  setSelectedBrokerageAccountId: (id: string | null) => void;
  setPortfolioViewMode: (mode: PortfolioViewMode) => void;
  setConnectModal: (v: boolean) => void;
  setExpiryNoticeOnLogin: (v: boolean) => void;
  setSymbol: (s: string) => void;
  setTimeframe: (t: string) => void;
  setExpiry: (e: string) => void;
  setRecommendedContract: (c: RecommendedContract | null) => void;
  captureSnapshot: (
    snap: ChartSnapshot,
    image?: string | null,
    frozen?: boolean,
    bars?: OhlcBar[],
    context?: OhlcBar[],
    daily?: OhlcBar[],
  ) => void;
}

export const useSession = create<SessionState>((set) => ({
  // Memory only — a full document load (reload / new tab / Cmd-R) remounts JS and plays splash again.
  splashSeen: false,
  user: null,
  accountMode: null,
  selectedBrokerageAccountId: null,
  portfolioViewMode: readPortfolioViewMode(),
  showConnectModal: false,
  expiryNoticeOnLogin: false,
  symbol: persistedScan.symbol ?? "SPX",
  timeframe: persistedScan.timeframe ?? "1D",
  expiry: persistedScan.expiry ?? "",
  recommendedContract: persistedScan.recommendedContract ?? null,
  snapshot: persistedScan.snapshot ?? null,
  chartImage: null,
  chartImageFrozen: false,
  capturedBars: persistedScan.capturedBars ?? [],
  visibleBars: persistedScan.capturedBars ?? [],
  capturedContext: persistedScan.capturedContext ?? [],
  capturedDaily: persistedScan.capturedDaily ?? [],
  markSplashSeen: () => set({ splashSeen: true }),
  // Auth refresh updates `user` only. symbol, expiry, capturedBars, and
  // recommendedContract stay so an in-progress scan survives re-authentication.
  setUser: (user) => set({ user, accountMode: user?.account_mode ?? null }),
  setSelectedBrokerageAccountId: (selectedBrokerageAccountId) => set({ selectedBrokerageAccountId }),
  setPortfolioViewMode: (portfolioViewMode) => {
    writePortfolioViewMode(portfolioViewMode);
    set({ portfolioViewMode });
  },
  setConnectModal: (showConnectModal) => set({ showConnectModal }),
  setExpiryNoticeOnLogin: (expiryNoticeOnLogin) => set({ expiryNoticeOnLogin }),
  setSymbol: (symbol) => set({ symbol }),
  setTimeframe: (timeframe) => set({ timeframe }),
  setExpiry: (expiry) => set({ expiry }),
  setRecommendedContract: (recommendedContract) => set({ recommendedContract }),
  captureSnapshot: (snapshot, chartImage = null, chartImageFrozen = false, capturedBars = [], capturedContext = [], capturedDaily = []) =>
    set({
      snapshot,
      chartImage,
      chartImageFrozen,
      capturedBars,
      visibleBars: capturedBars,
      capturedContext,
      capturedDaily,
    }),
}));

useSession.subscribe((state) => {
  writePersistedScan(state);
});

export function clearScanSession() {
  browserSessionStorage()?.removeItem(SCAN_SESSION_KEY);
  useSession.setState({
    symbol: "SPX",
    timeframe: "1D",
    expiry: "",
    recommendedContract: null,
    snapshot: null,
    chartImage: null,
    chartImageFrozen: false,
    capturedBars: [],
    visibleBars: [],
    capturedContext: [],
    capturedDaily: [],
  });
  browserSessionStorage()?.removeItem(SCAN_SESSION_KEY);
}

export function rehydrateScanSession() {
  const saved = readPersistedScan();
  const bars = saved.capturedBars ?? [];
  useSession.setState({
    symbol: saved.symbol ?? "SPX",
    timeframe: saved.timeframe ?? "1D",
    expiry: saved.expiry ?? "",
    recommendedContract: saved.recommendedContract ?? null,
    snapshot: saved.snapshot ?? null,
    capturedBars: bars,
    visibleBars: bars,
    capturedContext: saved.capturedContext ?? [],
    capturedDaily: saved.capturedDaily ?? [],
  });
}
