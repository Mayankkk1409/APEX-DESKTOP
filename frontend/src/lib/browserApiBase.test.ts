import { describe, expect, it } from "vitest";
import { browserApiBase } from "./browserApiBase";

describe("browserApiBase", () => {
  it("stays on the page when the API is the other loopback host", () => {
    expect(browserApiBase("http://localhost:8000", "http://127.0.0.1:5173")).toBe("");
    expect(browserApiBase("http://127.0.0.1:8000", "http://localhost:5173")).toBe("");
  });

  it("keeps a same-origin or public API", () => {
    expect(browserApiBase("", "http://127.0.0.1:5173")).toBe("");
    expect(browserApiBase("http://127.0.0.1:5173", "http://127.0.0.1:5173")).toBe("http://127.0.0.1:5173");
    expect(browserApiBase("https://api.example.com", "https://desk.example.com")).toBe("https://api.example.com");
  });
});
