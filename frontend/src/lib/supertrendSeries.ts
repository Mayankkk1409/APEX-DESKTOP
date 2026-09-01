import type { CanvasRenderingTarget2D } from "fancy-canvas";
import {
  customSeriesDefaultOptions,
  type CustomData,
  type CustomSeriesOptions,
  type CustomSeriesPricePlotValues,
  type ICustomSeriesPaneRenderer,
  type ICustomSeriesPaneView,
  type PaneRendererCustomData,
  type PriceToCoordinateConverter,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";

export interface SupertrendData extends CustomData<Time> {
  value: number;
  direction: 1 | -1;
}

export interface SupertrendSeriesOptions extends CustomSeriesOptions {
  upColor: string;
  downColor: string;
  lineWidth: number;
}

const defaults: SupertrendSeriesOptions = {
  ...customSeriesDefaultOptions,
  upColor: "#00c853",
  downColor: "#ff1744",
  lineWidth: 2,
} as SupertrendSeriesOptions;

/**
 * SuperTrend has to break the line wherever the trend flips, the same way
 * TradingView's `plot.style_linebr` does.
 *
 * It cannot be two plain line series with whitespace on the inactive bars:
 * a LineSeries joins straight across whitespace, which paints two full-width
 * lines (one green, one red) instead of one flipping line.
 */
class SupertrendRenderer implements ICustomSeriesPaneRenderer {
  private data: PaneRendererCustomData<Time, SupertrendData> | null = null;
  private options: SupertrendSeriesOptions | null = null;

  update(data: PaneRendererCustomData<Time, SupertrendData>, options: SupertrendSeriesOptions) {
    this.data = data;
    this.options = options;
  }

  draw(target: CanvasRenderingTarget2D, priceToCoordinate: PriceToCoordinateConverter) {
    const data = this.data;
    const options = this.options;
    const visible = data?.visibleRange;
    if (!data || !options || !visible || data.bars.length === 0) return;

    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.lineWidth = options.lineWidth;
      ctx.lineJoin = "round";
      ctx.lineCap = "butt";

      let run: { direction: 1 | -1; points: { x: number; y: number }[] } | null = null;
      const flush = () => {
        if (run && run.points.length > 1) {
          // Stepline (H then V) — never a free diagonal across the pane. Connecting
          // raw (x,y) pairs drew steep green/red rays whenever ATR jumped, which
          // looked like the old stray support diagonal.
          ctx.beginPath();
          ctx.strokeStyle = run.direction === 1 ? options.upColor : options.downColor;
          ctx.moveTo(run.points[0].x, run.points[0].y);
          for (let i = 1; i < run.points.length; i++) {
            const prev = run.points[i - 1];
            const cur = run.points[i];
            ctx.lineTo(cur.x, prev.y);
            ctx.lineTo(cur.x, cur.y);
          }
          ctx.stroke();
        }
        run = null;
      };

      // One bar of overscan on each side keeps the segment entering the viewport
      // anchored to its true neighbour instead of clipping to the edge.
      const from = Math.max(0, visible.from - 1);
      const to = Math.min(data.bars.length, visible.to + 1);

      for (let i = from; i < to; i++) {
        const bar = data.bars[i];
        const point = bar.originalData;
        if (!point || typeof point.value !== "number" || !Number.isFinite(point.value)) {
          flush();
          continue;
        }
        const y = priceToCoordinate(point.value);
        if (y === null) {
          flush();
          continue;
        }
        if (run && run.direction !== point.direction) flush();
        if (!run) run = { direction: point.direction, points: [] };
        run.points.push({ x: bar.x, y });
      }
      flush();
      ctx.restore();
    });
  }
}

export class SupertrendSeries implements ICustomSeriesPaneView<Time, SupertrendData, SupertrendSeriesOptions> {
  private readonly _renderer = new SupertrendRenderer();

  priceValueBuilder(plotRow: SupertrendData): CustomSeriesPricePlotValues {
    return [plotRow.value];
  }

  isWhitespace(data: SupertrendData | WhitespaceData<Time>): data is WhitespaceData<Time> {
    return typeof (data as Partial<SupertrendData>).value !== "number";
  }

  renderer(): ICustomSeriesPaneRenderer {
    return this._renderer;
  }

  update(data: PaneRendererCustomData<Time, SupertrendData>, options: SupertrendSeriesOptions): void {
    this._renderer.update(data, options);
  }

  defaultOptions(): SupertrendSeriesOptions {
    return defaults;
  }
}
