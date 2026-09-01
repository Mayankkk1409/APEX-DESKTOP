import { create } from "zustand";
import type { OhlcBar } from "./lib/ta";
import { readPortfolioViewMode, writePortfolioViewMode } from "./lib/portfolioViewMode";
import type { AccountMode, ChartSnapshot, PortfolioViewMode, RecommendedContract, User } from "./types";

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
  markSplashSeen: () => set({ splashSeen: true }),
  setUser: (user) => set({ user, accountMode: user?.account_mode ?? null }),
  setSelectedBrokerageAccountId: (selectedBrokerageAccountId) => set({ selectedBrokerageAccountId }),
  setPortfolioViewMode: (portfolioViewMode) => {
    writePortfolioViewMode(portfolioViewMode);
    set({ portfolioViewMode });
  },
  setConnectModal: (showConnectModal) => set({ showConnectModal }),
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
