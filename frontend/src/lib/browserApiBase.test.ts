import { describe, expect, it } from "vitest";
import { browserApiBase } from "./browserApiBase";

describe("browserApiBase", () => {
  it("calls the API on the page loopback host, never the other name", () => {
    expect(browserApiBase("http://localhost:8000", "http://127.0.0.1:5173")).toBe("http://127.0.0.1:8000");
    expect(browserApiBase("http://127.0.0.1:8000", "http://localhost:5173")).toBe("http://localhost:8000");
    expect(browserApiBase("ws://localhost:8000", "http://127.0.0.1:5173")).toBe("ws://127.0.0.1:8000");
  });

  it("keeps a same-origin or public API", () => {
    expect(browserApiBase("", "http://127.0.0.1:5173")).toBe("");
    expect(browserApiBase("http://127.0.0.1:5173", "http://127.0.0.1:5173")).toBe("http://127.0.0.1:5173");
    expect(browserApiBase("https://api.example.com", "https://desk.example.com")).toBe("https://api.example.com");
  });
});
