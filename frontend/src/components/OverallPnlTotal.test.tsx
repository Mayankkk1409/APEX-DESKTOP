import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OverallPnlTotal } from "./OverallPnlTotal";

describe("OverallPnlTotal", () => {
  it("renders a signed overall total with the up token class", () => {
    const html = renderToStaticMarkup(<OverallPnlTotal value={1500} />);
    expect(html).toContain('data-testid="overall-pnl-total"');
    expect(html).toContain("Overall total P&amp;L");
    expect(html).toContain("+$1,500");
    expect(html).toContain("num-up");
    expect(html).not.toContain("num-down");
  });

  it("colors a loss with the down token class", () => {
    const html = renderToStaticMarkup(<OverallPnlTotal value={-42.5} />);
    expect(html).toContain("-$42.5");
    expect(html).toContain("num-down");
    expect(html).not.toContain("num-up");
  });

  it("leaves a zero total uncolored", () => {
    const html = renderToStaticMarkup(<OverallPnlTotal value={0} />);
    expect(html).toContain("$0");
    expect(html).not.toContain("num-up");
    expect(html).not.toContain("num-down");
  });

  it("shows an em dash when the API did not provide a total", () => {
    const html = renderToStaticMarkup(<OverallPnlTotal value={null} />);
    expect(html).toContain("—");
    expect(html).not.toContain("num-up");
    expect(html).not.toContain("num-down");
  });
});
