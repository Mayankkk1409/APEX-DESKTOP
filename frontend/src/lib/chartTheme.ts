import { ColorType, type DeepPartial, type ChartOptions } from "lightweight-charts";

/** Read a CSS custom property from :root (computed). */
export function readCssColor(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function pnlChartLayoutOptions(): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: readCssColor("--apex-chart-bg", "#0b0d12") },
      textColor: readCssColor("--apex-text-muted", "#9aa0b0"),
    },
    grid: {
      vertLines: { color: readCssColor("--apex-chart-grid", "rgba(240,243,250,0.06)") },
      horzLines: { color: readCssColor("--apex-chart-grid", "rgba(240,243,250,0.06)") },
    },
    rightPriceScale: { borderColor: readCssColor("--apex-chart-border", "rgba(240,243,250,0.12)") },
    timeScale: { borderColor: readCssColor("--apex-chart-border", "rgba(240,243,250,0.12)") },
  };
}

export function pnlAreaSeriesColors() {
  return {
    lineColor: readCssColor("--apex-chart-line", "#e0b568"),
    topColor: readCssColor("--apex-chart-area-top", "rgba(224,181,104,0.35)"),
    bottomColor: readCssColor("--apex-chart-area-bottom", "rgba(224,181,104,0.02)"),
  };
}

export function ivHvChartLayoutOptions(): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { color: readCssColor("--apex-chart-bg", "#0b0d12") },
      textColor: readCssColor("--apex-subtle", "rgba(206,191,156,0.75)"),
    },
    grid: {
      vertLines: { color: readCssColor("--apex-chart-grid", "rgba(240,243,250,0.05)") },
      horzLines: { color: readCssColor("--apex-chart-grid", "rgba(240,243,250,0.05)") },
    },
    rightPriceScale: { borderColor: readCssColor("--apex-chart-border", "rgba(240,243,250,0.1)") },
    timeScale: { borderColor: readCssColor("--apex-chart-border", "rgba(240,243,250,0.1)") },
    crosshair: {
      vertLine: {
        color: readCssColor("--apex-chart-crosshair", "rgba(224,181,104,0.35)"),
        labelBackgroundColor: readCssColor("--apex-chart-crosshair-label", "#2a2110"),
      },
      horzLine: {
        color: readCssColor("--apex-chart-crosshair", "rgba(224,181,104,0.35)"),
        labelBackgroundColor: readCssColor("--apex-chart-crosshair-label", "#2a2110"),
      },
    },
  };
}
