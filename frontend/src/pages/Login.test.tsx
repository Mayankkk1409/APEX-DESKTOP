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
    expect(html).toContain('for="login-username"');
    expect(html).toContain('id="login-username"');
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
    expect(pathAfterSessionRestore("/dashboard")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/app")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/scan")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/portfolio")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/settings")).toBe("/portfolio");
    expect(pathAfterSessionRestore("/login")).toBe("/portfolio");
    expect(pathAfterSessionRestore(undefined)).toBe("/portfolio");
  });
});
