type Props = { size?: number; animate?: boolean; className?: string; src?: string; uncropped?: boolean };

const LOGO_SRC = "/brand/apex-logo.png";
const VIEW_W = 800;
const VIEW_H = 800;

export function ApexLogo({ size = 180, animate = false, className = "", src = LOGO_SRC, uncropped = false }: Props) {
  const height = Math.round((size * VIEW_H) / VIEW_W);

  if (!animate) {
    return (
      <img
        src={src}
        alt="APEX"
        width={size}
        height={height}
        className={`object-contain ${className}`}
        data-testid="apex-logo"
      />
    );
  }

  return (
    <div className={`apex-assemble ${className}`} style={{ width: size, height }} data-testid="apex-logo" role="img" aria-label="APEX">
      <div className="apex-glow" aria-hidden />
      <div className={uncropped ? "apex-draw-clip is-open" : "apex-draw-clip"}>
        <img src={src} alt="APEX" width={size} height={height} className="apex-draw-mark" draggable={false} />
        <div className="apex-draw-stroke" aria-hidden />
      </div>
    </div>
  );
}
