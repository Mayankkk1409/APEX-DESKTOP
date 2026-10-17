import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PLATFORM_TOUR_SRC, PlatformTourDialog } from "./PlatformTourDialog";

describe("PlatformTourDialog", () => {
  it("requires the tour dialog with skip and the video source", () => {
    const html = renderToStaticMarkup(<PlatformTourDialog onDismiss={() => undefined} />);
    expect(html).toContain('data-testid="platform-tour-dialog"');
    expect(html).toContain('data-testid="platform-tour-video"');
    expect(html).toContain('data-testid="platform-tour-skip"');
    expect(html).toContain("Skip");
    expect(html).toContain(PLATFORM_TOUR_SRC);
    expect(PLATFORM_TOUR_SRC).toBe("/brand/apex-platform-tour.mp4");
  });
});
