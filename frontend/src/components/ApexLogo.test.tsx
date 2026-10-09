import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApexLogo } from "./ApexLogo";

describe("ApexLogo", () => {
  it("uses the public brand file at the square size with an APEX name", () => {
    const html = renderToStaticMarkup(<ApexLogo size={36} className="shrink-0" />);
    expect(html).toContain('src="/brand/apex-logo.png"');
    expect(html).toContain('alt="APEX"');
    expect(html).toContain('width="36"');
    expect(html).toContain('height="36"');
    expect(html).toContain('data-testid="apex-logo"');
    expect(html).toContain("shrink-0");
  });

  it("keeps the assemble animation on the same asset", () => {
    const html = renderToStaticMarkup(<ApexLogo size={80} animate />);
    expect(html).toContain('data-testid="apex-logo"');
    expect(html).toContain('aria-label="APEX"');
    expect(html).toContain('src="/brand/apex-logo.png"');
    expect(html).toContain('alt="APEX"');
    expect(html).toContain('width="80"');
    expect(html).toContain('height="80"');
    expect(html).toContain("apex-assemble");
  });

  it("points the document favicon at the same file", () => {
    const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
    expect(html).toContain('rel="icon"');
    expect(html).toContain('href="/brand/apex-logo.png"');
  });
});
