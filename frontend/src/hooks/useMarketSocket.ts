import { useEffect, useRef, useState } from "react";
import { getAccessToken, subscribeAccessToken } from "../api";
import { WS_BASE } from "../constants";
import { connectMarketSocket, marketSocketUrl, type MarketSocketMessage } from "../lib/marketSocket";

/**
 * Dashboard fill/quote socket. Reconnects after the API process reloads.
 * A proxy EPIPE is a dropped subscription, not a failed trade.
 */
export function useMarketSocket(opts: {
  token: string | null;
  symbols?: string[];
  onMessage: (msg: MarketSocketMessage) => void;
}) {
  const onMessageRef = useRef(opts.onMessage);
  onMessageRef.current = opts.onMessage;
  const symbolsRef = useRef(opts.symbols);
  symbolsRef.current = opts.symbols;
  const sendRef = useRef<(data: string) => boolean>(() => false);
  const symbolKey = (opts.symbols ?? []).filter(Boolean).join(",");
  const [liveToken, setLiveToken] = useState<string | null>(opts.token);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setLiveToken(opts.token);
  }, [opts.token]);

  useEffect(() => subscribeAccessToken(setLiveToken), []);

  useEffect(() => {
    const token = liveToken || getAccessToken();
    if (!token || typeof WebSocket === "undefined") return;
    const conn = connectMarketSocket({
      url: marketSocketUrl(WS_BASE, token),
      getToken: getAccessToken,
      urlForToken: (next) => marketSocketUrl(WS_BASE, next),
      getSymbols: () => symbolsRef.current ?? [],
      onMessage: (msg) => onMessageRef.current(msg),
      onState: setConnected,
    });
    sendRef.current = conn.send;
    return () => {
      sendRef.current = () => false;
      conn.close();
    };
  }, [liveToken]);

  useEffect(() => {
    if (!symbolKey) return;
    sendRef.current(JSON.stringify({ type: "subscribe", symbols: symbolKey.split(",") }));
  }, [liveToken, symbolKey]);

  return { connected };
}
