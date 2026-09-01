import logoPng from "../assets/apex-logo.png";

type Props = { size?: number; animate?: boolean; className?: string };

const VIEW_W = 507;
const VIEW_H = 492;

export function ApexLogo({ size = 180, animate = false, className = "" }: Props) {
  const height = Math.round((size * VIEW_H) / VIEW_W);

  if (!animate) {
    return (
      <img
        src={logoPng}
        alt="APEX"
        width={size}
        height={height}
        className={`object-contain ${className}`}
        data-testid="apex-logo"
      />
    );
  }

  return (
    <div className={`apex-assemble ${className}`} style={{ width: size, height }} data-testid="apex-logo">
      <div className="apex-glow" aria-hidden />
      <div className="apex-draw-clip">
        <img src={logoPng} alt="APEX" width={size} height={height} className="apex-draw-mark" draggable={false} />
        <div className="apex-draw-stroke" aria-hidden />
      </div>
    </div>
  );
}
