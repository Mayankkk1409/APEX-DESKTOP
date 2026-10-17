/** Keep a dragged card inside the window, matching the info score card margins. */
export function clampCardPoint(x: number, y: number, viewportWidth: number, viewportHeight: number) {
  return {
    x: Math.min(viewportWidth - 96, Math.max(8, x)),
    y: Math.min(viewportHeight - 64, Math.max(8, y)),
  };
}
