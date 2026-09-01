import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type { IPanePrimitive, IPanePrimitivePaneView, ISeriesApi, SeriesType, Time } from "lightweight-charts";

export type PivotLabelRow = { label: string; price: number };

/**
 * Left-anchored pivot labels, matching "Labels position: Left" in the
 * Pivot Points Standard settings. The library's own price-line titles render on
 * the right next to the price scale, which is the wrong side for this config.
 *
 * Implemented as a pane primitive so the labels are repainted by the chart
 * itself on every zoom, pan, vertical scale change and data update.
 */
export class PivotLabelsPrimitive implements IPanePrimitive<Time> {
  private readonly views: readonly IPanePrimitivePaneView[];

  constructor(
    private readonly getSeries: () => ISeriesApi<SeriesType, Time> | null,
    private readonly getRows: () => PivotLabelRow[],
    private readonly color: string,
  ) {
    this.views = [
      {
        zOrder: () => "top",
        renderer: () => ({ draw: (target: CanvasRenderingTarget2D) => this.draw(target) }),
      },
    ];
  }

  paneViews(): readonly IPanePrimitivePaneView[] {
    return this.views;
  }

  updateAllViews(): void {
    /* labels are derived from live coordinates on every draw */
  }

  private draw(target: CanvasRenderingTarget2D) {
    const series = this.getSeries();
    const rows = this.getRows();
    if (!series || !rows.length) return;
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      ctx.save();
      ctx.font = "11px 'Trebuchet MS', 'IBM Plex Sans', system-ui, sans-serif";
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      for (const row of rows) {
        const y = series.priceToCoordinate(row.price);
        if (y == null || !Number.isFinite(y)) continue;
        if (y < 10 || y > mediaSize.height - 6) continue;
        const width = ctx.measureText(row.label).width;
        ctx.fillStyle = "rgba(11, 13, 18, 0.78)";
        ctx.fillRect(5, y - 8, width + 8, 16);
        ctx.fillStyle = this.color;
        ctx.fillText(row.label, 9, y);
      }
      ctx.restore();
    });
  }
}
