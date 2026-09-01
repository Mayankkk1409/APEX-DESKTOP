import { describe, expect, it } from "vitest";
import { advancedChartSrc, TV_EMBED_STUDIES, tvSymbol, tvWidgetConfig } from "./tv";

describe("tvSymbol", () => {
  it("maps AAPL to NASDAQ and SPX to a free-widget index feed, never SPY", () => {
    expect(tvSymbol("AAPL")).toBe("NASDAQ:AAPL");
    expect(tvSymbol("SPX")).toBe("FOREXCOM:SPXUSD");
    expect(tvSymbol("SPX")).not.toContain("SPY");
    expect(tvSymbol("AAPL")).not.toBe("AMEX:SPY");
  });
});

describe("TV_EMBED_STUDIES", () => {
  it("fills the five free-widget slots with EMA9, EMA21, BB, MACD, RSI", () => {
    const ids = TV_EMBED_STUDIES.map((s) => (typeof s === "string" ? s : s.id));
    expect(ids).toEqual([
      "MAExp@tv-basicstudies",
      "MAExp@tv-basicstudies",
      "BB@tv-basicstudies",
      "MACD@tv-basicstudies",
      "RSI@tv-basicstudies",
    ]);
    expect(TV_EMBED_STUDIES).toHaveLength(5);
    const ema9 = TV_EMBED_STUDIES[0];
    const ema21 = TV_EMBED_STUDIES[1];
    expect(typeof ema9).toBe("object");
    expect(typeof ema21).toBe("object");
    if (typeof ema9 === "object") expect(ema9.inputs.length).toBe(9);
    if (typeof ema21 === "object") expect(ema21.inputs.length).toBe(21);
  });
});

describe("advancedChartSrc", () => {
  it("targets tradingview-widget.com advanced-chart with study inputs in the hash", () => {
    const src = advancedChartSrc("AAPL", "1D", "desk");
    expect(src.startsWith("https://www.tradingview-widget.com/embed-widget/advanced-chart/")).toBe(true);
    const hash = decodeURIComponent(src.split("#")[1] ?? "");
    const cfg = JSON.parse(hash) as ReturnType<typeof tvWidgetConfig>;
    expect(cfg.symbol).toBe("NASDAQ:AAPL");
    expect(cfg.interval).toBe("D");
    expect(cfg.hide_top_toolbar).toBe(false);
    expect(cfg.hide_side_toolbar).toBe(false);
    expect(cfg.withdateranges).toBe(true);
    expect(cfg.studies).toHaveLength(5);
    expect(cfg.studies[0]).toEqual({ id: "MAExp@tv-basicstudies", inputs: { length: 9 } });
    expect(cfg.studies[1]).toEqual({ id: "MAExp@tv-basicstudies", inputs: { length: 21 } });
    expect(cfg.studies[3]).toEqual({ id: "MACD@tv-basicstudies", inputs: {} });
    expect(cfg.studies[4]).toEqual({ id: "RSI@tv-basicstudies", inputs: { length: 14 } });
  });

  it("strips chrome for frozen scan snapshots", () => {
    const cfg = tvWidgetConfig("AAPL", "1D", "frozen");
    expect(cfg.hide_top_toolbar).toBe(true);
    expect(cfg.hide_side_toolbar).toBe(true);
    expect(cfg.withdateranges).toBe(false);
    expect(cfg.studies).toHaveLength(5);
  });
});
