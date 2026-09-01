import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Login } from "./Login";

describe("Login", () => {
  it("renders forgot-password entry point on sign-in", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    expect(html).toContain('data-testid="forgot-password-link"');
    expect(html).toContain("Forgot password?");
  });
});
