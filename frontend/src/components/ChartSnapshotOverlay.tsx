import type { ChartHighlight } from "../lib/chartHighlight";

/** SVG glow / mark layer aligned to the frozen snapshot PNG (object-fit: contain). */
export function ChartSnapshotOverlay({
  highlight,
  width,
  height,
}: {
  highlight: ChartHighlight | null;
  width: number;
  height: number;
}) {
  if (!highlight || width < 8 || height < 8) return null;

  const filterId = `apex-glow-${highlight.id.replace(/[^a-z0-9-]/gi, "")}`;

  return (
    <svg
      className="ta-snapshot-overlay"
      data-testid="chart-snapshot-overlay"
      data-highlight-id={highlight.id}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
    >
      <defs>
        <filter id={filterId} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {highlight.glowPanes?.map((pane, i) => (
        <g key={`pane-${i}`} filter={`url(#${filterId})`}>
          <rect
            x={pane.x}
            y={pane.y}
            width={pane.w}
            height={pane.h}
            fill="none"
            stroke={pane.color}
            strokeWidth={2.5}
            strokeOpacity={0.92}
            rx={4}
          />
          <rect x={pane.x} y={pane.y} width={pane.w} height={pane.h} fill={pane.color} fillOpacity={0.07} rx={4} />
        </g>
      ))}

      {highlight.glowLines?.map((line, i) => (
        <polyline
          key={`line-${i}`}
          points={line.xs.map((x, j) => `${x},${line.ys[j]}`).join(" ")}
          fill="none"
          stroke={line.color}
          strokeWidth={line.width + 2}
          strokeOpacity={0.35}
          filter={`url(#${filterId})`}
        />
      ))}
      {highlight.glowLines?.map((line, i) => (
        <polyline
          key={`line-core-${i}`}
          points={line.xs.map((x, j) => `${x},${line.ys[j]}`).join(" ")}
          fill="none"
          stroke={line.color}
          strokeWidth={line.width}
          strokeOpacity={0.95}
        />
      ))}

      {highlight.mark?.kind === "circle" && (
        <g data-testid="chart-mark-circle" filter={`url(#${filterId})`}>
          <circle
            cx={highlight.mark.cx}
            cy={highlight.mark.cy}
            r={highlight.mark.r}
            fill="none"
            stroke={highlight.mark.color}
            strokeWidth={2.5}
            strokeOpacity={0.95}
          />
          <circle cx={highlight.mark.cx} cy={highlight.mark.cy} r={highlight.mark.r * 0.55} fill={highlight.mark.color} fillOpacity={0.12} />
        </g>
      )}

      {highlight.mark?.kind === "box" && (
        <g data-testid="chart-mark-box" filter={`url(#${filterId})`}>
          <rect
            x={highlight.mark.x}
            y={highlight.mark.y}
            width={highlight.mark.w}
            height={highlight.mark.h}
            fill="none"
            stroke={highlight.mark.color}
            strokeWidth={2.5}
            strokeOpacity={0.95}
            rx={3}
          />
          <rect
            x={highlight.mark.x}
            y={highlight.mark.y}
            width={highlight.mark.w}
            height={highlight.mark.h}
            fill={highlight.mark.color}
            fillOpacity={0.1}
            rx={3}
          />
        </g>
      )}
    </svg>
  );
}
