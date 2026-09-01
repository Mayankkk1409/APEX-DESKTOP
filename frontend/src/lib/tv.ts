/** TradingView Advanced Chart helpers. */

const INDEX_SYMBOLS: Record<string, string> = {
  // Free Advanced Chart widget rejects some index feeds with "only available on TradingView".
  // FOREXCOM:SPXUSD loads on the free widget; remount uses query-string src (not hash).
  SPX: "FOREXCOM:SPXUSD",
  SPXUSD: "FOREXCOM:SPXUSD",
  DJI: "FOREXCOM:DJI",
  DJIA: "FOREXCOM:DJI",
  NDX: "FOREXCOM:NSXUSD",
  RUT: "TVC:RUT",
  VIX: "TVC:VIX",
  COMP: "TVC:IXIC",
  IXIC: "TVC:IXIC",
};

const EQUITY_SYMBOLS: Record<string, string> = {
  AAPL: "NASDAQ:AAPL",
  MSFT: "NASDAQ:MSFT",
  NVDA: "NASDAQ:NVDA",
  AMZN: "NASDAQ:AMZN",
  META: "NASDAQ:META",
  GOOG: "NASDAQ:GOOG",
  GOOGL: "NASDAQ:GOOGL",
  TSLA: "NASDAQ:TSLA",
  AMD: "NASDAQ:AMD",
  NFLX: "NASDAQ:NFLX",
  INTC: "NASDAQ:INTC",
  AVGO: "NASDAQ:AVGO",
  COST: "NASDAQ:COST",
  PEP: "NASDAQ:PEP",
  CSCO: "NASDAQ:CSCO",
  QCOM: "NASDAQ:QCOM",
  AMAT: "NASDAQ:AMAT",
  ADBE: "NASDAQ:ADBE",
  PYPL: "NASDAQ:PYPL",
  QQQ: "NASDAQ:QQQ",
  TQQQ: "NASDAQ:TQQQ",
  SQQQ: "NASDAQ:SQQQ",
  IWM: "AMEX:IWM",
  DIA: "AMEX:DIA",
  SPY: "AMEX:SPY",
  SPYG: "AMEX:SPYG",
  SPYV: "AMEX:SPYV",
  GLD: "AMEX:GLD",
  SLV: "AMEX:SLV",
  TLT: "NASDAQ:TLT",
  HYG: "AMEX:HYG",
  EEM: "AMEX:EEM",
  EFA: "AMEX:EFA",
  XLF: "AMEX:XLF",
  XLE: "AMEX:XLE",
  XLK: "AMEX:XLK",
  XLV: "AMEX:XLV",
  XLI: "AMEX:XLI",
  XLP: "AMEX:XLP",
  XLY: "AMEX:XLY",
  XLU: "AMEX:XLU",
  XLB: "AMEX:XLB",
  JPM: "NYSE:JPM",
  BAC: "NYSE:BAC",
  WFC: "NYSE:WFC",
  C: "NYSE:C",
  GS: "NYSE:GS",
  V: "NYSE:V",
  MA: "NYSE:MA",
  WMT: "NYSE:WMT",
  JNJ: "NYSE:JNJ",
  XOM: "NYSE:XOM",
  CVX: "NYSE:CVX",
  UNH: "NYSE:UNH",
  PG: "NYSE:PG",
  HD: "NYSE:HD",
  KO: "NYSE:KO",
  DIS: "NYSE:DIS",
  IBM: "NYSE:IBM",
  GE: "NYSE:GE",
  CAT: "NYSE:CAT",
  BA: "NYSE:BA",
  MMM: "NYSE:MMM",
  MRK: "NYSE:MRK",
  PFE: "NYSE:PFE",
  NKE: "NYSE:NKE",
  MCD: "NYSE:MCD",
  VZ: "NYSE:VZ",
  T: "NYSE:T",
  "BRK.B": "NYSE:BRK.B",
  "BRK.A": "NYSE:BRK.A",
};

const INTERVAL: Record<string, string> = {
  "1m": "1",
  "5m": "5",
  "15m": "15",
  "1H": "60",
  "4H": "240",
  "1D": "D",
  "1W": "W",
};

export function tvSymbol(symbol: string): string {
  const s = symbol.trim().toUpperCase();
  if (!s) return "AMEX:SPY";
  if (s.includes(":")) {
    const bare = s.split(":")[1] ?? s;
    if (INDEX_SYMBOLS[bare]) return INDEX_SYMBOLS[bare];
    return s;
  }
  if (INDEX_SYMBOLS[s]) return INDEX_SYMBOLS[s];
  if (EQUITY_SYMBOLS[s]) return EQUITY_SYMBOLS[s];
  return `NASDAQ:${s}`;
}

export function tvInterval(timeframe: string): string {
  return INTERVAL[timeframe] ?? "D";
}

/**
 * Free Advanced Chart widget hard-caps ~5 studies.
 * MACD + RSI occupy two slots as full sub-panes; remaining three are
 * EMA 9, EMA 21, and Bollinger 20/2. Volume is native (not a study slot).
 * EMA 50/100/200 are drawn as TradingView-style overlays on the price pane
 * (see ChartOverlay). SuperTrend and pivots are not drawn on the desk chart.
 */
export const TV_EMBED_STUDIES = [
  { id: "MAExp@tv-basicstudies", inputs: { length: 9 } },
  { id: "MAExp@tv-basicstudies", inputs: { length: 21 } },
  { id: "BB@tv-basicstudies", inputs: { length: 20, mult: 2 } },
  { id: "MACD@tv-basicstudies", inputs: {} },
  { id: "RSI@tv-basicstudies", inputs: { length: 14 } },
];

export type ChartChrome = "desk" | "frozen";

/** Official free Advanced Chart widget config (studies with inputs — not ID-only query strings). */
export function tvWidgetConfig(symbol: string, timeframe: string, chrome: ChartChrome = "desk") {
  const frozen = chrome === "frozen";
  return {
    autosize: true,
    symbol: tvSymbol(symbol),
    interval: tvInterval(timeframe),
    timezone: "America/New_York",
    theme: "dark" as const,
    style: "1",
    locale: "en",
    backgroundColor: "#131722",
    gridColor: "rgba(240, 243, 250, 0.06)",
    hide_top_toolbar: frozen,
    hide_side_toolbar: frozen,
    hide_legend: false,
    withdateranges: !frozen,
    allow_symbol_change: false,
    save_image: false,
    hide_volume: false,
    calendar: false,
    support_host: "https://www.tradingview.com",
    studies: TV_EMBED_STUDIES,
  };
}

/**
 * tradingview-widget.com Advanced Chart embed URL.
 * Full JSON (including study inputs for EMA 9 / EMA 21) lives in the hash.
 * Callers MUST remount a fresh iframe on ticker/timeframe change — mutating only
 * the hash on an existing iframe does not reload the widget.
 */
export function advancedChartSrc(symbol: string, timeframe: string, chrome: ChartChrome = "desk"): string {
  const cfg = tvWidgetConfig(symbol, timeframe, chrome);
  const hash = encodeURIComponent(JSON.stringify(cfg));
  return `https://www.tradingview-widget.com/embed-widget/advanced-chart/?locale=${cfg.locale}#${hash}`;
}

/**
 * Mount via a fresh iframe pointing at tradingview-widget.com/embed-widget/advanced-chart.
 * Object-form studies (EMA 9 / 21 inputs, MACD + RSI panes) apply reliably this way.
 * Remount by clearing the container (React key on ticker/tf/chrome).
 */
export function mountAdvancedChart(container: HTMLElement, symbol: string, timeframe: string, chrome: ChartChrome) {
  container.innerHTML = "";

  const widget = document.createElement("div");
  widget.className = "tradingview-widget-container__widget";
  widget.style.cssText = "width:100%;height:100%;";
  container.appendChild(widget);

  const iframe = document.createElement("iframe");
  iframe.title = `${tvSymbol(symbol)} chart`;
  iframe.src = advancedChartSrc(symbol, timeframe, chrome);
  iframe.setAttribute("data-testid", "tv-iframe");
  iframe.setAttribute("data-tv-embed", "advanced-chart");
  iframe.allow = "fullscreen";
  iframe.style.cssText = "width:100%;height:100%;border:0;display:block;background:#131722;";
  widget.appendChild(iframe);
}
