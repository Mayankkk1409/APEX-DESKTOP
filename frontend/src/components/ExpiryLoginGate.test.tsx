import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ExpiryLoginGate } from "./ExpiryLoginGate";
import { useSession } from "../store";

describe("ExpiryLoginGate", () => {
  it("does not cover the desk while the reminder is still loading", () => {
    useSession.setState({ expiryLoginPending: true });
    const html = renderToStaticMarkup(<ExpiryLoginGate />);
    expect(html).not.toContain("expiry-login-hold");
    expect(html).not.toContain("inset-0");
    useSession.setState({ expiryLoginPending: false });
  });
});
