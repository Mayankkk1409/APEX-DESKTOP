import { API_BASE } from "../constants";
import { getAccessToken, refreshAccessTokenOnce } from "../api";

export type BrokerageAccount = {
  id: string;
  account_name: string;
  account_type: string;
  broker_name: string;
  account_number_masked: string;
  sync_status: string;
  last_synced_at: string | null;
};

export type BrokerageBalance = {
  cash_balance: number;
  buying_power: number;
  total_equity: number;
  day_pnl: number | null;
  currency: string;
  as_of_timestamp: string;
};

export type BrokeragePosition = {
  symbol: string;
  quantity: number;
  average_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  currency: string;
  day_pnl?: number | null;
};

async function brokerageReq<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new Error("Cannot reach APEX API. Make sure the backend is running on port 8000.");
  }
  if (res.status === 401 && !retried) {
    const next = await refreshAccessTokenOnce();
    if (next) return brokerageReq<T>(path, init, true);
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
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const brokerageApi = {
  registerUser: () => brokerageReq<{ ok: boolean; connection_status: string }>("/api/brokerage/register-user", { method: "POST" }),
  sync: () => brokerageReq<{ ok: boolean; connection_status: string; account_count: number }>("/api/brokerage/sync", { method: "POST" }),
  portalUrl: (broker?: string) =>
    brokerageReq<{ url: string }>("/api/brokerage/connection-portal-url", {
      method: "POST",
      body: JSON.stringify({ broker: broker ?? null }),
    }),
  accounts: () => brokerageReq<{ connection_status: string | null; accounts: BrokerageAccount[] }>("/api/brokerage/accounts"),
  balance: (accountId: string) => brokerageReq<BrokerageBalance>(`/api/brokerage/accounts/${encodeURIComponent(accountId)}/balance`),
  positions: (accountId: string) =>
    brokerageReq<{ positions: BrokeragePosition[] }>(`/api/brokerage/accounts/${encodeURIComponent(accountId)}/positions`),
  disconnect: (accountId: string) =>
    brokerageReq<void>(`/api/brokerage/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" }),
};
