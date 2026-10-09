import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Login, pathAfterSessionRestore } from "./Login";

describe("Login", () => {
  it("renders forgot-password entry point on sign-in", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Login skipSessionRestore />
      </MemoryRouter>,
    );
    expect(html).toContain('data-testid="forgot-password-link"');
    expect(html).toContain("Forgot password?");
  });

  it("checks the refresh cookie before showing the form", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    expect(html).toContain('data-testid="session-restore"');
    expect(html).not.toContain('data-testid="login-form"');
  });

  it("sends a reload back to every signed-in screen", () => {
    expect(pathAfterSessionRestore("/app")).toBe("/app");
    expect(pathAfterSessionRestore("/scan")).toBe("/scan");
    expect(pathAfterSessionRestore("/portfolio")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/settings")).toBe("/settings");
    expect(pathAfterSessionRestore("/login")).toBe("/app");
    expect(pathAfterSessionRestore(undefined)).toBe("/app");
  });
});
