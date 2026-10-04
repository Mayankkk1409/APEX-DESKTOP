import { API_BASE } from "./constants";
import type {
  ChainAnalysis,
  ChartSnapshot,
  Fundamentals,
  FundamentalsLayer,
  NewsArticleContent,
  Quote,
  RecommendedContract,
  SentimentLayer,
  VolatilityEvents,
  VolatilitySeries,
  VolatilitySnapshot,
} from "./types";

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export const AUTH_REDIRECT_KEY = "apex_auth_redirect";

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new Error("Cannot reach APEX API. Make sure the backend is running on port 8000.");
  }
  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    if (res.status >= 500 && (detail === "Internal Server Error" || detail === res.statusText)) {
      detail = "Brokerage service error. Try Refresh — if it persists, restart the backend.";
    }
    if (res.status === 401) {
      setAccessToken(null);
      const msg = typeof detail === "string" ? detail : "Session expired — please sign in again.";
      sessionStorage.setItem(AUTH_REDIRECT_KEY, msg);
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ market_adapter: string; data_feed: string }>("/health"),
  signup: (body: Record<string, unknown>) => req("/auth/signup", { method: "POST", body: JSON.stringify(body) }),
  login: (username: string, password: string) =>
    req("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  otpRequest: (username: string) =>
    req<{ ok: boolean; ttl_seconds: number; autofill: boolean; code: string | null }>("/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ username }),
    }),
  otpVerify: (username: string, code: string) =>
    req<{
      access_token: string;
      brokerage_connected: boolean;
      first_login: boolean;
      account_mode: string;
      show_connect_modal: boolean;
    }>("/auth/otp/verify", { method: "POST", body: JSON.stringify({ username, code }) }),
  forgotPassword: (username: string, password: string, confirm_password: string) =>
    req<{ ok: boolean; ttl_seconds: number; autofill: boolean; code: string | null }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ username, password, confirm_password }),
    }),
  forgotPasswordVerify: (username: string, code: string) =>
    req<{
      access_token: string;
      brokerage_connected: boolean;
      first_login: boolean;
      account_mode: string;
      show_connect_modal: boolean;
    }>("/auth/forgot-password/verify", { method: "POST", body: JSON.stringify({ username, code }) }),
  me: () => req("/auth/me"),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  brokerage: (later: boolean) => req("/auth/brokerage", { method: "POST", body: JSON.stringify({ later }) }),
  dismissBanner: () => req("/auth/brokerage/banner/dismiss", { method: "POST" }),
  strength: (password: string) => req<{ score: number; label: string }>("/auth/password-strength", { method: "POST", body: JSON.stringify({ password }) }),
  quote: (symbol: string) => req<Quote>(`/market/quote/${encodeURIComponent(symbol)}`),
  fundamentals: (symbol: string) => req<Fundamentals>(`/market/fundamentals/${encodeURIComponent(symbol)}`),
  fundamentalsDeep: (symbol: string) =>
    req<FundamentalsLayer>(`/market/fundamentals/${encodeURIComponent(symbol)}/deep`),
  sentimentDeep: (symbol: string, expiry?: string) => {
    const q = expiry ? `?expiry=${encodeURIComponent(expiry)}` : "";
    return req<SentimentLayer>(`/market/sentiment/${encodeURIComponent(symbol)}${q}`);
  },
  newsArticle: (url: string, fallbackText?: string | null) => {
    const params = new URLSearchParams({ url });
    if (fallbackText?.trim()) params.set("fallback_text", fallbackText.trim());
    return req<NewsArticleContent>(`/market/news/article?${params.toString()}`);
  },
  search: (q: string) => req<{ hits: { symbol: string; name: string }[] }>(`/market/search?q=${encodeURIComponent(q)}`),
  expirations: (symbol: string) => req<{ expirations: { date: string; dte: number; kind: string; near_expiry: boolean }[] }>(`/market/expirations/${symbol}`),
  options: (symbol: string, expiry: string) => req(`/market/options/${symbol}?expiry=${expiry}`),
  optionsAnalysis: (
    symbol: string,
    expiry: string,
    opts: { spreadMaxPct?: number; vegaCapOverride?: boolean; structureAbsorbsGamma?: boolean } = {},
  ) => {
    const params = new URLSearchParams({ expiry });
    if (opts.spreadMaxPct !== undefined) params.set("spread_max_pct", String(opts.spreadMaxPct));
    if (opts.vegaCapOverride) params.set("vega_cap_override", "true");
    if (opts.structureAbsorbsGamma) params.set("structure_absorbs_gamma", "true");
    return req<ChainAnalysis>(`/market/options/${encodeURIComponent(symbol)}/analysis?${params.toString()}`);
  },
  feed: () => req<{ adapter: string; feed: string; alpaca_keys: boolean; default_symbol: string }>("/market/feed"),
  indicators: (symbol: string, timeframe: string) =>
    req<{
      ema: Record<string, number>;
      rsi: number;
      supertrend: { value: number; direction: string; atr: number };
      bollinger: { mid: number; upper: number; lower: number; width: number };
      macd: { line: number; signal: number; histogram: number };
    }>(`/market/indicators/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}`),
  bars: (symbol: string, timeframe: string, limit = 400) =>
    req<{ symbol: string; timeframe: string; bars: { t: string; o: number; h: number; l: number; c: number; v: number }[] }>(
      `/market/bars/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
    ),
  watchlist: () => req<{ items: { symbol: string; name: string; price: number; change_pct: number }[] }>("/watchlist"),
  addWatch: (symbol: string) => req("/watchlist", { method: "POST", body: JSON.stringify({ symbol }) }),
  removeWatch: (symbol: string) => req(`/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  sentiment: (symbol?: string) => {
    const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
    return req<{
      items: import("./types").SentimentRow[];
      fear_greed: number | null;
      label: string;
      status?: string;
      caveat?: string | null;
      symbol?: string | null;
      score_method?: string | null;
      news_provider?: string | null;
    }>(`/sentiment${q}`);
  },
  portfolio: () => req<import("./types").PortfolioSummary>("/api/portfolio"),
  pnlHistory: () => req<import("./types").PnlHistory>("/api/portfolio/pnl-history"),
  overallPnl: () => req<{ rows: import("./types").OverallPnlRow[] }>("/api/portfolio/overall-pnl"),
  positions: () => req<{ positions: import("./types").PositionRow[] }>("/api/positions"),
  positionDetail: (positionId: string) =>
    req<{
      position: import("./types").PositionRow;
      certificate: {
        strategy_name?: string | null;
        entry_composite_score?: number | null;
        greeks?: { delta?: number | null; gamma?: number | null; theta?: number | null; vega?: number | null };
        legs?: import("./types").StrategyLeg[];
        breakevens?: import("./types").BreakevenValue[];
        breakeven_iv_assumption?: boolean;
        breakeven_assumption_note?: string;
        max_loss?: number | null;
        max_profit?: number | null;
        net_debit_credit?: number | null;
        net_type?: string | null;
      };
    }>(`/api/positions/${encodeURIComponent(positionId)}`),
  closePosition: (positionId: string) =>
    req<{ ok: boolean; balance: number; buying_power: number; portfolio_value: number }>(
      `/api/positions/${encodeURIComponent(positionId)}/close`,
      { method: "POST" },
    ),
  orderHistory: () => req<{ orders: import("./types").OrderHistoryRow[] }>("/api/orders"),
  order: (body: Record<string, unknown>) => req("/api/orders", { method: "POST", body: JSON.stringify(body) }),
  scan: (snapshot: ChartSnapshot, expiry?: string) =>
    req("/scan", { method: "POST", body: JSON.stringify({ snapshot, expiry }) }),
  layers: () => req<{ layers: string[] }>("/scan/layers"),
  volatility: (symbol: string, expiry?: string, recommended?: RecommendedContract | null) => {
    const params = new URLSearchParams();
    if (expiry) params.set("expiry", expiry);
    if (recommended) params.set("recommended_contract", JSON.stringify(recommended));
    const q = params.toString() ? `?${params.toString()}` : "";
    return req<VolatilitySnapshot>(`/volatility/${encodeURIComponent(symbol)}${q}`);
  },
  volatilitySeries: (symbol: string, expiry?: string, recommended?: RecommendedContract | null) => {
    const params = new URLSearchParams();
    if (expiry) params.set("expiry", expiry);
    if (recommended) params.set("recommended_contract", JSON.stringify(recommended));
    const q = params.toString() ? `?${params.toString()}` : "";
    return req<VolatilitySeries>(`/volatility/${encodeURIComponent(symbol)}/series${q}`);
  },
  volatilityEvents: (symbol: string) => req<VolatilityEvents>(`/volatility/${encodeURIComponent(symbol)}/events`),
  brokerageRegister: () => req<{ ok: boolean; connection_status: string }>("/api/brokerage/register-user", { method: "POST" }),
  brokerageSync: () => req<{ ok: boolean; connection_status: string; account_count: number }>("/api/brokerage/sync", { method: "POST" }),
  brokeragePortalUrl: (broker?: string) =>
    req<{ url: string }>("/api/brokerage/connection-portal-url", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  brokerageAccounts: () => req<{ connection_status: string | null; accounts: unknown[] }>("/api/brokerage/accounts"),
  brokerageBalance: (accountId: string) =>
    req(`/api/brokerage/accounts/${encodeURIComponent(accountId)}/balance`),
  brokeragePositions: (accountId: string) =>
    req<{ positions: unknown[] }>(`/api/brokerage/accounts/${encodeURIComponent(accountId)}/positions`),
  brokerageEquityHistory: (accountId: string) =>
    req<import("./types").PnlHistory>(`/api/brokerage/accounts/${encodeURIComponent(accountId)}/equity-history`),
  brokerageOrders: (accountId: string) =>
    req<{ orders: import("./types").OrderHistoryRow[] }>(
      `/api/brokerage/accounts/${encodeURIComponent(accountId)}/orders`,
    ),
  brokerageDisconnect: (accountId: string) =>
    req(`/api/brokerage/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" }),
  /** Persist user preferences — falls back to localStorage when endpoint is unavailable. */
  syncSettings: (body: Record<string, unknown>) =>
    req<{ ok: boolean }>("/api/settings/trading", {
      method: "PATCH",
      body: JSON.stringify({
        auto_execution_threshold: body.autoExecMinScore,
        risk_profile: body.riskProfile,
        max_risk_per_trade_pct: body.maxRiskPerTradePct,
        max_positions: body.maxPositions,
        theme_preference: body.theme,
      }),
    }).catch(() => ({ ok: false })),
  getSettings: () => req<Record<string, unknown>>("/api/settings/trading").catch(() => null),
  resetPaperBalance: (starting_balance: number) =>
    req<import("./types").User>("/api/settings/paper-balance", {
      method: "PATCH",
      body: JSON.stringify({ balance: starting_balance, reason: "User reset from settings" }),
    }).then(async (res) => {
      const me = await req<import("./types").User>("/auth/me");
      return me;
    }),
  deleteAccount: (password?: string) =>
    req<{ ok: boolean; deleted: boolean }>("/api/settings/account/delete", {
      method: "POST",
      body: JSON.stringify({ password: password ?? "" }),
    }),
};
