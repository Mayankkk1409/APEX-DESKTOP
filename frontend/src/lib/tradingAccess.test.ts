import { describe, expect, it } from "vitest";
import { realBrokerageSource } from "./tradingAccess";

describe("realBrokerageSource", () => {
  it("allows paper trading when the signup was real brokerage but the source is paper", () => {
    expect(realBrokerageSource({ viewMode: "paper", brokerageConnected: false })).toBe(false);
    expect(realBrokerageSource({ viewMode: "paper", brokerageConnected: true })).toBe(false);
  });

  it("blocks trading only while a connected real brokerage is the source", () => {
    expect(realBrokerageSource({ viewMode: "brokerage", brokerageConnected: false })).toBe(false);
    expect(realBrokerageSource({ viewMode: "brokerage", brokerageConnected: true })).toBe(true);
  });
});
