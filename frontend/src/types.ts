export type AccountMode = "paper_funded" | "real_brokerage";

/** Which portfolio data source the dashboard and portfolio pages display. */
export type PortfolioViewMode = "paper" | "brokerage";

export interface User {
  id: string;
  full_name: string;
  username: string;
  email: string;
  account_mode: AccountMode;
  brokerage_connected: boolean;
  connect_later_banner: boolean;
  first_login_completed: boolean;
  cash_balance: number;
  buying_power: number;
  portfolio_value: number;
  starting_balance: number | null;
}

export interface Quote {
  symbol: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  avg_volume: number | null;
  week_52_high: number | null;
  week_52_low: number | null;
  market_cap: number | null;
  pe_ttm: number | null;
  div_yield: number | null;
  expense_ratio: number | null;
  beta_5y: number | null;
  source: string;
  secondary_source: string | null;
  status?: "live" | "partial" | "unavailable";
  as_of?: string | null;
  asset_class?: string | null;
}

export interface Fundamentals {
  symbol: string;
  name: string;
  market_cap: number | null;
  pe_ttm: number | null;
  div_yield: number | null;
  expense_ratio: number | null;
  beta_5y: number | null;
  avg_volume: number | null;
  source: string;
  status: "live" | "partial" | "unavailable";
  as_of: string | null;
  asset_class: string | null;
}

export interface Expiration {
  date: string;
  dte: number;
  kind: string;
  near_expiry: boolean;
  earnings_highlight: boolean;
}

/** Where a Greek or IV number came from. `model` = locally computed Black-Scholes. */
export type ValueSource = "vendor" | "model" | "unavailable";

export type ChainStatus =
  | "live"
  | "vendor_quotes_model_greeks"
  | "simulated"
  | "no_entitlement"
  | "no_keys"
  | "unsupported_underlying"
  | "empty"
  | "unavailable";

export type GateStatus = "pass" | "fail" | "warn" | "unknown";

export type ContractVerdictKind =
  | "buy_candidate"
  | "sell_candidate"
  | "tradeable"
  | "screened_out"
  | "rejected"
  | "insufficient_data";

export interface Gate {
  id: string;
  label: string;
  status: GateStatus;
  rule: string;
  observed: string;
  detail: string;
}

export interface ContractVerdict {
  symbol: string;
  strike: number;
  side: "call" | "put";
  verdict: ContractVerdictKind;
  hard_reject: boolean;
  moneyness: "itm" | "atm" | "otm" | "unknown";
  dte: number;
  mid: number | null;
  spread_abs: number | null;
  spread_pct_of_mid: number | null;
  delta_theta_ratio: number | null;
  theta_pct_of_mid: number | null;
  vega_pct_of_mid: number | null;
  gamma_delta_shift_1pct: number | null;
  volume_oi_ratio: number | null;
  itm_probability_proxy: number | null;
  breakeven: number | null;
  buy_score: number | null;
  sell_score: number | null;
  gates: Gate[];
  flags: string[];
  reasons: string[];
  reasoning: string;
  greeks_source: ValueSource;
}

/** Every market datum is nullable — a missing bid is rendered as missing, never as 0.00. */
export interface OptionContract {
  symbol: string;
  strike: number;
  side: "call" | "put";
  bid: number | null;
  ask: number | null;
  bid_size: number | null;
  ask_size: number | null;
  last: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  open_interest: number | null;
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  rho: number | null;
  greeks_source: ValueSource;
  iv_source: ValueSource;
  quote_as_of: string | null;
}

export interface ChainContractRow extends OptionContract {
  verdict: ContractVerdict | null;
}

export interface ChainDataSource {
  status: ChainStatus;
  label: string;
  is_live: boolean;
  source: string;
  feed: string;
  greeks_source: ValueSource;
  as_of: string | null;
  vendor_greeks: number;
  model_greeks: number;
  missing_greeks: number;
  caveats: string[];
}

export interface ChainAnalysisCard {
  id: string;
  title: string;
  verdict: string;
  bias: "bullish" | "bearish" | "neutral";
  body: string;
}

export interface ChainThresholds {
  buy_delta_min: number;
  sell_delta_max: number;
  rule1_delta_min: number;
  rule1_theta_max: number;
  rule2_delta_max: number;
  delta_theta_buy_min: number;
  delta_theta_sell_max: number;
  spread_max_pct_of_mid: number;
  spread_max_pct_illiquid: number;
  min_open_interest: number;
  volume_oi_min_ratio: number;
  uoa_volume_multiple: number;
  gamma_dte_flag: number;
}

export interface ChainSummary {
  contract_count: number;
  call_count: number;
  put_count: number;
  single_sided: boolean;
  put_call_oi_ratio?: number | null;
  put_call_volume_ratio?: number | null;
  atm_iv?: number | null;
  hv?: number | null;
  iv_rank_proxy?: number | null;
  iv_skew_25d?: number | null;
  max_pain?: { strike: number; intrinsic_owed: number } | null;
  median_spread_pct?: number | null;
  verdict_counts: Partial<Record<ContractVerdictKind, number>>;
  gate_failures: Record<string, number>;
  gate_unknown: Record<string, number>;
  unusual_activity: ContractVerdict[];
  vega_cap_blocked: string[];
  gamma_flagged: string[];
}

export interface RecommendedContract {
  symbol: string;
  expiry: string;
  strike: number;
  side: "call" | "put";
  contract_id: string | null;
}

export interface ChainAnalysis {
  title: string;
  symbol: string;
  expiry: string | null;
  expiry_valid: boolean;
  dte: number | null;
  spot: number | null;
  spot_source: string | null;
  atm_strike: number | null;
  recommendedContract: RecommendedContract | null;
  execution_score?: number | null;
  execution_tier?: "blocked" | "caution" | "auto_exec" | null;
  data_source: ChainDataSource;
  thresholds: ChainThresholds;
  vega_cap: {
    catalyst_environment: boolean;
    reason: string;
    override_granted: boolean;
    structure_absorbs_gamma: boolean;
    blocks_long_premium: boolean;
  };
  contracts: ChainContractRow[];
  summary: ChainSummary;
  cards: ChainAnalysisCard[];
  narrative: string;
}

export interface ChartSnapshot {
  symbol: string;
  timeframe: string;
  visible_from: string;
  visible_to: string;
  studies: string[];
  captured_at: string;
}

export interface ApexScoreBreakdown {
  label: string;
  value: unknown;
  note?: string;
}

export interface ApexScoreSection {
  id: string;
  title: string;
  score: number;
  weight: number;
  weighted_contribution: number;
  narrative: string;
  paragraphs?: string[];
  interpretation?: string;
  breakdown?: ApexScoreBreakdown[];
}

export interface ApexScoreLayer {
  title: string;
  composite_score: number;
  threshold_full_doc: number;
  threshold_project_apex?: number;
  clears_threshold: boolean;
  weights: Record<string, number>;
  sections: ApexScoreSection[];
  narrative: string;
  paragraphs?: string[];
  interpretation?: string;
}

export interface StrategyLeg {
  action: string;
  side?: string;
  strike?: number;
  expiry?: string;
  mid?: number | null;
  symbol?: string;
  quantity?: number;
  order_type?: string;
  limit_basis?: string | null;
  limit_price?: number | null;
}

/** Calendar spreads may return a breakeven band instead of a single strike. */
export interface BreakevenRange {
  type: "range";
  lower: number;
  upper: number;
  iv_assumption?: boolean;
}

export type BreakevenValue = number | BreakevenRange;

export interface StrategyMetrics {
  max_loss: number | null;
  max_profit: number | null;
  net_debit_credit: number | null;
  net_type: string | null;
  breakevens: BreakevenValue[];
  legs: StrategyLeg[];
  per_contract_multiplier?: number;
  notes?: string;
  /** When true, breakeven range depends on IV assumptions (calendar spreads). */
  breakeven_iv_assumption?: boolean;
  breakeven_assumption_note?: string;
  /** Registry allows unlimited max profit display (long call, straddle, APEX Strategy). */
  max_profit_unlimited_allowed?: boolean;
  /** Undefined-risk structures: the unbounded loss side is Unlimited, not a scanned stand-in. */
  max_loss_unlimited_allowed?: boolean;
  /** Calendars, diagonals, butterflies, and ratios: do not render a scanned max profit. */
  payoff_depends_on_remaining_leg?: boolean;
  validation_error?: string | null;
  equity_covered_by_holdings?: boolean;
  greeks?: { delta?: number | null; gamma?: number | null; theta?: number | null; vega?: number | null };
  payoff_grid?: {
    underlying: number;
    pnl: number;
  }[];
  capital_required?: number | null;
}

export interface StrategyLayer {
  title: string;
  tradeable?: boolean;
  execution_tier?: "blocked" | "caution" | "auto_exec" | null;
  selected_strategy: string;
  composite_score?: number;
  clears_threshold?: boolean;
  direction?: string;
  vol_signal?: string;
  vol_regime?: string | null;
  recommended_contract?: RecommendedContract | null;
  equity_required?: boolean;
  equity_overlay_only?: boolean;
  equity_note?: string | null;
  what_is_this: string;
  why_recommended: string;
  why_it_fits?: string;
  outlook?: string;
  strategies_evaluated?: number | null;
  selection_rationale?: string | null;
  risk_notes?: string[];
  validation_errors?: Array<{ check?: string; expected?: string; actual?: string }>;
  auto_exec_line?: string | null;
  auto_exec_blocked?: boolean;
  auto_execute_eligible?: boolean;
  structure_label?: string | null;
  placeable?: boolean;
  quote_not_current?: boolean;
  quote_as_of?: string | null;
  block_reason?: string | null;
  checks_passed?: boolean;
  execution_banner?: string | null;
  how_to_execute: string;
  metrics: StrategyMetrics;
  narrative: string;
}

export interface ScanResult {
  id: string;
  symbol: string;
  composite_score: number;
  recommendedContract?: RecommendedContract | null;
  layers: string[];
  layer_data: Record<string, Record<string, unknown>>;
}

export interface PositionRow {
  id: string;
  symbol: string;
  qty: number;
  avg_cost: number;
  current: number;
  unrealized_pl: number;
  market_value: number;
  /** Intraday P&L when provided by brokerage or computed from quote change. */
  day_pl?: number | null;
  asset_class?: string;
  strategy_name?: string | null;
}

export interface OrderHistoryRow {
  id: string;
  symbol: string;
  side: string;
  qty: number;
  order_type: string;
  fill_price: number | null;
  status: string;
  asset_class: string;
  created_at: string | null;
  filled_at: string | null;
}

/** POST /api/orders response — single leg or multi-leg strategy fill. */
export interface OrderPlacementResult {
  id: string;
  status: string;
  fill_price: number | null;
  estimated_cost?: number;
  account_impact?: number;
  balance?: number;
  buying_power?: number;
  portfolio_value?: number;
  asset_class: string;
  legs_filled?: OrderLegFill[];
}

export interface OrderLegFill {
  id: string;
  symbol: string;
  side: string;
  qty: number;
  fill_price?: number | null;
  asset_class?: string;
  order_type?: string;
}

export interface OrderConfirmationDetails {
  orderIds: string[];
  legs: OrderLegFill[];
  strategyName: string;
  accountLabel: string;
  accountMode?: AccountMode | null;
  ticker: string;
  orderType: string;
  assetClass: string;
  status?: string;
}

export interface OverallPnlRow {
  symbol: string;
  asset_class: string;
  qty: number;
  realized_pl: number;
  unrealized_pl: number;
  total_pl: number;
  is_open: boolean;
  /** Present only when the source reported a fee. Omitted means no fee was provided. */
  fees?: number | null;
}

export interface PnlPoint {
  t: string;
  portfolio_value: number;
  balance?: number;
  cumulative_pl?: number;
}

export interface PnlHistory {
  starting_balance: number;
  account_mode: string;
  points: PnlPoint[];
}

export interface PortfolioSummary {
  balance: number;
  buying_power: number;
  portfolio_value: number;
  starting_balance?: number;
  day_pl?: number;
  day_pct?: number;
  account_mode?: string;
  top_movers?: { symbol: string; unrealized_pl?: number }[];
}

export interface WatchItem {
  symbol: string;
  name: string;
  price: number | null;
  change_pct: number | null;
}

export interface SentimentRow {
  headline: string;
  blurb: string;
  source: string;
  signal: string;
  score: number | null;
  score_method?: string | null;
  published_at: string;
  symbol: string | null;
  url?: string | null;
}

export interface NewsArticleContent {
  status: "ok" | "fallback" | "error";
  url: string;
  title?: string | null;
  byline?: string | null;
  body?: string | null;
  body_html?: string | null;
  excerpt?: string | null;
  method?: string;
  error?: string | null;
}

export interface SentimentArticle {
  headline: string | null;
  summary: string | null;
  content?: string | null;
  source: string | null;
  author: string | null;
  url: string | null;
  published_at: string | null;
  symbols: string[];
  nlp_score: number | null;
  nlp_method: string;
}

export interface SentimentLayer {
  title: string;
  symbol: string;
  score: number | null;
  score_0_100: number | null;
  band?: string;
  bias: string;
  weights: Record<string, number>;
  weights_applied: Record<string, number>;
  components: {
    news: {
      status: string;
      score: number | null;
      count: number;
      method: string;
      source: string | null;
      as_of?: string | null;
      error?: string | null;
      articles: SentimentArticle[];
    };
    options_flow: {
      status: string;
      score: number | null;
      label: string;
      window: string;
      volume_context?: string;
      notional_skew?: string;
      call_volume: number | null;
      put_volume: number | null;
      put_call_volume_ratio?: number | null;
      put_call_signal?: string;
      call_notional_proxy: number | null;
      put_notional_proxy: number | null;
      net_notional_proxy: number | null;
      unusual_activity_count: number | null;
      source: string | null;
      expiry?: string | null;
    };
    social: {
      status: string;
      score: number | null;
      label: string;
      source: string | null;
      caveat?: string;
    };
    put_call: {
      status: string;
      score: number | null;
      ratio: number | null;
      signal: string;
      rule: string;
      source: string | null;
      basis: string;
    };
  };
  earnings_alert: {
    active: boolean;
    dte: number | null;
    next_date: string | null;
    message: string;
    source: string | null;
  };
  evidence: Record<string, unknown>;
  narrative: string;
}

export interface FundFactorCard {
  id: string;
  title: string;
  body: string;
}

export interface FundamentalsLayer {
  title: string;
  symbol: string;
  name: string;
  score: number;
  sources: string[];
  as_of: string;
  factor_cards?: FundFactorCard[];
  eps_trend: {
    status: string;
    source: string | null;
    consecutive_beats: number | null;
    trend: string;
    latest: {
      fiscal_quarter?: string | null;
      date_reported?: string | null;
      eps?: number | null;
      consensus?: number | null;
      surprise_pct?: number | null;
    } | null;
    history: Array<{
      fiscal_quarter?: string | null;
      date_reported?: string | null;
      eps?: number | null;
      consensus?: number | null;
      surprise_pct?: number | null;
    }>;
  };
  revenue: {
    status: string;
    source: string | null;
    yoy_pct: number | null;
    signal: string | null;
    current: number | null;
    prior: number | null;
    period_current?: string | null;
    period_prior?: string | null;
    units?: string;
    rule?: string;
  };
  net_income: {
    current: number | null;
    prior: number | null;
    yoy_pct: number | null;
    source: string | null;
  };
  earnings_calendar: {
    status: string;
    next_date: string | null;
    dte: number | null;
    last_reported: string | null;
    source: string | null;
    caveat?: string | null;
    vendor_note?: string | null;
  };
  analyst: {
    status: string;
    source: string | null;
    price_target: number | null;
    low_target?: number | null;
    high_target?: number | null;
    buy: number | null;
    hold: number | null;
    sell: number | null;
    coverage: number | null;
    consensus_label: string | null;
  };
  sector_rotation: {
    status: string;
    source: string | null;
    sector?: string | null;
    etf?: string | null;
    sector_return_pct?: number | null;
    spy_return_pct?: number | null;
    relative_pct?: number | null;
    flow?: string | null;
    reading?: string | null;
    caveat?: string | null;
  };
  profile: {
    status: string;
    sector: string | null;
    industry: string | null;
    company_name?: string | null;
  };
  company_health: {
    eps_latest: number | null;
    eps_consensus_last: number | null;
    eps_surprise_pct: number | null;
    revenue: number | null;
    revenue_yoy_pct: number | null;
    net_income: number | null;
    net_income_yoy_pct: number | null;
    pe_ttm: number | null;
    market_cap: number | null;
    week_52_high: number | null;
    week_52_low: number | null;
    avg_volume: number | null;
    div_yield: number | null;
    beta_5y: number | null;
    analyst_target: number | null;
    analyst_upside_pct: number | null;
    analyst_coverage: number | null;
    spot: number | null;
  };
}

export interface VolatilityCard {
  id: string;
  title: string;
  bias?: string;
  body: string;
}

export interface VolatilityExpectedMove {
  dollars: number | null;
  percent: number | null;
  up: number | null;
  down: number | null;
}

export interface VolatilitySeries {
  symbol?: string;
  expiry?: string | null;
  windows?: string[];
  windows_available: string[];
  hv_series: Record<string, { t: string; hv: number | null }[]>;
  iv_series?: { t: string; iv: number | null }[];
  current_iv?: number | null;
  bar_count?: number;
  methodology?: Record<string, string>;
  notes?: string[];
}

export interface VolatilitySnapshot {
  title: string;
  symbol: string;
  expiry: string | null;
  dte: number | null;
  spot: number | null;
  atm_strike: number | null;
  atm_iv?: number | null;
  iv: number | null;
  contract_iv?: number | null;
  recommended_contract?: RecommendedContract | null;
  hv: number | null;
  hv_by_window: Record<string, number | null>;
  iv_rank: number | null;
  iv_percentile: number | null;
  iv_history_points?: number | null;
  iv_history_source?: string | null;
  hv_rank: number | null;
  hv_percentile: number | null;
  hv_history_points?: number | null;
  expected_move: VolatilityExpectedMove;
  iv_vs_hv?: { signal: string; gap_pts: number | null; reason: string };
  signal?: string;
  series?: VolatilitySeries;
  cards: VolatilityCard[];
  methodology?: Record<string, string>;
  notes?: string[];
  narrative?: string;
  chain_status?: string | null;
}

export interface CatalystEvent {
  id: string;
  scope: "ticker" | "market";
  kind: string;
  symbol: string | null;
  title: string;
  detail: string;
  event_date: string;
  event_time: string;
  source: string;
  as_of: string;
}

export interface VolatilityEvents {
  symbol: string;
  ticker_events: CatalystEvent[];
  market_events: CatalystEvent[];
  sources: string[];
  as_of: string;
  notes: string[];
}
