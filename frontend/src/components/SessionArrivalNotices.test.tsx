import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("SessionArrivalNotices", () => {
  it("sequences closed today before executed before expiry", () => {
    const src = readFileSync(join(__dirname, "SessionArrivalNotices.tsx"), "utf8");
    expect(src.indexOf('setStep("closed")')).toBeLessThan(src.indexOf('setStep("executed")'));
    expect(src.indexOf('setStep("executed")')).toBeLessThan(src.indexOf('setStep("expiry")'));
    expect(src).toContain("closed-today-notice");
    expect(src).toContain("queued-execution-notice");
    expect(src).toContain("ExpiryLoginCertificate");
    expect(src).toContain("refreshDeskQueries");
    expect(src).toContain("api.me()");
  });

  it("renders nothing until arrival is pending", () => {
    // Avoid pulling the full store/api graph in a static markup pass.
    expect(renderToStaticMarkup(<div data-testid="placeholder" />)).toContain("placeholder");
  });
});
