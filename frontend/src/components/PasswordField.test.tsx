import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PasswordField } from "./PasswordField";

describe("PasswordField", () => {
  it("renders masked input with show-password toggle", () => {
    const html = renderToStaticMarkup(
      <PasswordField label="Password" testid="password" value="secret" onChange={() => {}} />,
    );
    expect(html).toContain('type="password"');
    expect(html).toContain('data-testid="password"');
    expect(html).toContain('data-testid="password-toggle"');
    expect(html).toContain("Show password");
  });
});
