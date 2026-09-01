import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ApexScoreScan } from "../components/ApexScoreScan";
import { FundamentalsScan } from "../components/FundamentalsScan";
import { OptionsChainGreeks } from "../components/OptionsChainGreeks";
import { OrderConfirmationCertificate } from "../components/OrderConfirmationCertificate";
import { SentimentScan } from "../components/SentimentScan";
import { StrategyScan } from "../components/StrategyScan";
import { TaSnapshot } from "../components/TaSnapshot";
import { VolatilityScan } from "../components/volatility/VolatilityScan";
import { CAROUSEL_LAYERS, SCAN_SLIDE_LAYERS, SNAPSHOT_STUDIES } from "../constants";
import { scoreTier } from "../lib/chartHighlight";
import { normalizeStrategyName } from "../lib/strategyDisplay";
import { readUserSettings } from "../lib/userSettings";
import { formatOrderAccountLabel, formatOrderType, buildOrderConfirmationDetails } from "../lib/orderFormat";
import type { OhlcBar } from "../lib/ta";
import { useSession } from "../store";
import type {
  ApexScoreLayer,
  ChainAnalysis,
  FundamentalsLayer,
  OrderConfirmationDetails,
  OrderPlacementResult,
  ScanResult,
  SentimentLayer,
  StrategyLayer,
  VolatilitySnapshot,
} from "../types";

const INTRO_MS = 2200;

export function DeepScan() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const {
    symbol,
    timeframe,
    expiry,
    snapshot,
    chartImage,
    chartImageFrozen,
    capturedBars,
    capturedContext,
    capturedDaily,
    captureSnapshot,
    setRecommendedContract,
    user,
    accountMode,
  } = useSession();
  const [intro, setIntro] = useState(true);
  const [idx, setIdx] = useState(0);
  const [thesis, setThesis] = useState(false);
  const [contractsPerLeg, setContractsPerLeg] = useState(1);
  const [msg, setMsg] = useState("");
  const [orderConfirmation, setOrderConfirmation] = useState<OrderConfirmationDetails | null>(null);

  const locked = useMemo(() => {
    if (snapshot) return snapshot;
    const nowIso = new Date().toISOString();
    const snap = {
      symbol,
      timeframe,
      visible_from: capturedBars[0]?.t ?? "",
      visible_to: capturedBars[capturedBars.length - 1]?.t ?? "",
      studies: SNAPSHOT_STUDIES,
      captured_at: nowIso,
    };
    captureSnapshot(snap, chartImage, chartImageFrozen, capturedBars, capturedContext, capturedDaily);
    return snap;
  }, [captureSnapshot, capturedBars, capturedContext, capturedDaily, chartImage, chartImageFrozen, snapshot, symbol, timeframe]);

  const scan = useQuery({
    queryKey: ["scan", locked.captured_at, locked.symbol, locked.timeframe, expiry],
    queryFn: () => api.scan(locked, expiry || undefined) as Promise<ScanResult>,
  });

  /**
   * Fallback only: if the user deep-links to /scan without a captured chart there
   * is nothing frozen to analyse, so refetch the same symbol/timeframe.
   */
  const barsQ = useQuery({
    queryKey: ["scan-bars", locked.symbol, locked.timeframe],
    queryFn: () => api.bars(locked.symbol, locked.timeframe, 600),
    enabled: capturedBars.length === 0,
  });

  const fallbackBars = useMemo(() => (barsQ.data?.bars ?? []) as OhlcBar[], [barsQ.data]);
  const plotBars = capturedBars.length ? capturedBars : fallbackBars;
  const contextBars = capturedContext.length ? capturedContext : fallbackBars;
  const windowFrom = locked.visible_from || plotBars[0]?.t || "";
  const windowTo = locked.visible_to || plotBars[plotBars.length - 1]?.t || "";

  useEffect(() => {
    const t = window.setTimeout(() => setIntro(false), INTRO_MS);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    const fromScan = scan.data?.recommendedContract;
    const fromLayer = (scan.data?.layer_data?.options_chain_greeks as ChainAnalysis | undefined)?.recommendedContract;
    const chainTier = (scan.data?.layer_data?.options_chain_greeks as ChainAnalysis | undefined)?.execution_tier;
    const pick = chainTier === "blocked" ? null : fromScan ?? fromLayer ?? null;
    setRecommendedContract(pick);
  }, [scan.data, setRecommendedContract]);

  const userSettings = useMemo(() => readUserSettings(), []);
  const autoExecMinScore = userSettings.autoExecMinScore;

  const compositeScore = scan.data?.composite_score ?? null;
  const riskReview = scan.data?.layer_data?.risk_review as
    | {
        execution_tier?: "blocked" | "caution" | "auto_exec";
        auto_submit_on_ack?: boolean;
        requires_place_order?: boolean;
        allows_execution?: boolean;
        auto_execution_threshold?: number;
        strategy_legs?: Array<{
          symbol: string;
          side: string;
          qty?: number;
          strike?: number;
          option_side?: string;
          expiry?: string;
        }>;
        contracts_per_leg?: number;
      }
    | undefined;
  const scanAutoThreshold = riskReview?.auto_execution_threshold ?? autoExecMinScore;
  const executionTier = riskReview?.execution_tier ?? scoreTier(compositeScore, scanAutoThreshold);
  const strategyLegs = riskReview?.strategy_legs ?? [];
  const allowsExecution = riskReview?.allows_execution ?? (executionTier !== "blocked" && strategyLegs.length > 0);
  const autoSubmitOnAck =
    Boolean(riskReview?.auto_submit_on_ack) &&
    executionTier === "auto_exec" &&
    userSettings.autoExecEnabled;
  const requiresPlaceOrder =
    executionTier === "caution" ||
    (executionTier === "auto_exec" && !userSettings.autoExecEnabled);
  const orderAssetClass = (riskReview as { asset_class?: string } | undefined)?.asset_class ?? "us_option";
  const orderTypeLabel = formatOrderType("market", orderAssetClass);
  const strategyName =
    (scan.data?.layer_data?.strategy as StrategyLayer | undefined)?.selected_strategy ?? "";

  function confirmationFromResult(result: OrderPlacementResult): OrderConfirmationDetails {
    return buildOrderConfirmationDetails(result, {
      strategyName,
      ticker: locked.symbol,
      user,
      accountMode,
      orderAssetClass,
    });
  }

  const layers = useMemo(() => {
    const all = scan.data?.layers ?? [];
    if (!all.length) return [...SCAN_SLIDE_LAYERS];
    return SCAN_SLIDE_LAYERS.filter((name) => all.includes(name));
  }, [scan.data?.layers]);
  // Keep slider index in range when the filtered slide list shrinks after scan loads.
  useEffect(() => {
    setIdx((i) => Math.min(i, Math.max(layers.length - 1, 0)));
  }, [layers.length]);

  const current = layers[idx] ?? layers[0];
  const data = current ? scan.data?.layer_data[current] : undefined;
  /**
   * Slide order (SCAN_SLIDE_LAYERS): technical → options_chain_greeks → volatility →
   * sentiment → fundamentals → apex_score → strategy → risk_review.
   * Rich UIs own their slides; only risk_review uses the narrative order panel.
   */
  const technical = !layers.length || current === "technical";
  const chainLayer = current === "options_chain_greeks";
  const volLayer = current === "volatility";
  const sentimentLayer = current === "sentiment";
  const fundamentalsLayer = current === "fundamentals";
  const apexScoreLayer = current === "apex_score";
  const strategyLayer = current === "strategy";
  const riskLayer = current === "risk_review";
  // Full-width slides that run their own card carousel and own the arrow keys.
  const ownsArrows = !layers.length || CAROUSEL_LAYERS.includes(current ?? "");
  const fullWidth =
    technical || chainLayer || volLayer || sentimentLayer || fundamentalsLayer || apexScoreLayer || strategyLayer;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (ownsArrows && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") setIdx((i) => Math.min(i + 1, Math.max(layers.length - 1, 0)));
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") setIdx((i) => Math.max(i - 1, 0));
      if (e.key === "Home") setIdx(0);
      if (e.key === "End") setIdx(Math.max(layers.length - 1, 0));
      if (e.key === "Escape") nav("/app");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [layers.length, nav, ownsArrows]);

  const order = useMutation({
    mutationFn: () => {
      if (!strategyLegs.length) {
        throw new Error("No options legs available for this scan — re-run with a tradeable strategy.");
      }
      return api.order({
        scan_id: scan.data?.id,
        thesis_accepted: thesis,
        asset_class: "us_option",
        legs: strategyLegs.map((leg) => ({
          symbol: leg.symbol,
          side: leg.side,
          qty: leg.qty ?? contractsPerLeg,
          strike: leg.strike,
          option_side: leg.option_side,
          expiry: leg.expiry,
        })),
        contracts_per_leg: contractsPerLeg,
      });
    },
    onSuccess: (r) => {
      const result = r as OrderPlacementResult;
      setOrderConfirmation(confirmationFromResult(result));
      void qc.invalidateQueries({ queryKey: ["port"] });
      void qc.invalidateQueries({ queryKey: ["pos"] });
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["pnl-history"] });
      void qc.invalidateQueries({ queryKey: ["overall-pnl"] });
    },
    onError: (e) => setMsg((e as Error).message),
  });

  if (intro) {
    return <ScanIntro symbol={locked.symbol} />;
  }

  return (
    <main className={`min-h-screen px-6 py-6 ${fullWidth ? "max-w-none" : ""}`} data-testid="deep-scan">
      <div className="mb-4 flex items-center justify-between">
        <button className="text-sm text-bronze" onClick={() => nav("/app")}>
          ← Dashboard
        </button>
        <p className="font-mono text-xs text-bronze" data-testid="snapshot-header">
          Snapshot {locked.symbol} · {locked.timeframe}
          {expiry ? ` · expiry ${expiry}` : ""} · {plotBars.length} bars · {windowFrom.slice(0, 10)} → {windowTo.slice(0, 10)} ·{" "}
          {locked.studies.length} studies locked
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button aria-label="Previous layer" data-testid="prev-layer" className="rounded-md border border-line px-3 py-2" onClick={() => setIdx((i) => Math.max(0, i - 1))}>
          ‹
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(layers.length - 1, 0)}
          value={idx}
          data-testid="layer-slider"
          className="flex-1 accent-gold"
          onChange={(e) => setIdx(Number(e.target.value))}
        />
        <button aria-label="Next layer" data-testid="next-layer" className="rounded-md border border-line px-3 py-2" onClick={() => setIdx((i) => Math.min(layers.length - 1, i + 1))}>
          ›
        </button>
      </div>
      <p className="mt-2 text-center text-xs uppercase tracking-[0.25em] text-gold" data-testid="layer-name">
        {idx + 1} / {layers.length} · {current?.replaceAll("_", " ")}
      </p>

      {technical ? (
        <section className="mt-4" data-testid="technical-layer">
          <TaSnapshot
            symbol={locked.symbol}
            timeframe={locked.timeframe}
            bars={plotBars}
            contextBars={contextBars}
            dailyBars={capturedDaily}
            from={windowFrom}
            to={windowTo}
            chartImage={chartImage}
          />
        </section>
      ) : chainLayer ? (
        <section className="mt-4" data-testid="options-chain-greeks-layer">
          <OptionsChainGreeks
            symbol={locked.symbol}
            expiry={expiry}
            initial={data as unknown as ChainAnalysis | undefined}
            executionScore={compositeScore}
          />
        </section>
      ) : volLayer ? (
        <section className="mt-4" data-testid="volatility-scan-layer">
          <VolatilityScan
            symbol={locked.symbol}
            expiry={expiry}
            initial={data as unknown as VolatilitySnapshot | undefined}
          />
        </section>
      ) : sentimentLayer ? (
        <section className="mt-4" data-testid="sentiment-layer">
          <SentimentScan
            symbol={locked.symbol}
            expiry={expiry}
            initial={data as unknown as SentimentLayer | undefined}
          />
        </section>
      ) : fundamentalsLayer ? (
        <section className="mt-4" data-testid="fundamentals-layer">
          <FundamentalsScan
            symbol={locked.symbol}
            initial={data as unknown as FundamentalsLayer | undefined}
          />
        </section>
      ) : apexScoreLayer ? (
        <section className="mt-4" data-testid="apex-score-layer">
          <ApexScoreScan initial={data as unknown as ApexScoreLayer | undefined} />
        </section>
      ) : strategyLayer ? (
        <section className="mt-4" data-testid="strategy-layer">
          <StrategyScan
            symbol={locked.symbol}
            expiry={expiry || undefined}
            initial={data as unknown as StrategyLayer | undefined}
          />
        </section>
      ) : (
        <AnimatePresence mode="wait">
          <motion.section
            key={current}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mx-auto mt-6 max-w-4xl rounded-2xl border border-line bg-panel p-6"
          >
            <h1 className="font-display text-3xl">{String(data?.title ?? current)}</h1>
            <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-champagne/80">{String(data?.narrative ?? "Loading…")}</p>
            {riskLayer && (
              <div className="mt-6 space-y-4" data-testid="risk-review" data-execution-tier={executionTier}>
                {executionTier === "blocked" || !allowsExecution ? (
                  <p className="text-sm text-champagne/80" data-testid="risk-blocked">
                    Execution is blocked for this scan (composite ≤50 or no tradeable options legs). Review prior layers and
                    re-scan when conviction improves.
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-champagne/70">
                      Options-only execution — {strategyLegs.length} leg{strategyLegs.length === 1 ? "" : "s"} from the
                      recommended strategy. Each leg is submitted as an OCC options contract order.
                    </p>
                    <ul className="space-y-2 text-sm" data-testid="strategy-legs-review">
                      {strategyLegs.map((leg) => (
                        <li key={leg.symbol} className="rounded border border-line/60 px-3 py-2 font-mono text-xs">
                          {leg.side.toUpperCase()} {contractsPerLeg} × {leg.symbol}
                          {leg.option_side && leg.strike != null
                            ? ` (${leg.option_side} ${leg.strike}${leg.expiry ? ` · ${leg.expiry}` : ""})`
                            : ""}
                        </li>
                      ))}
                    </ul>
                    <label className="flex cursor-pointer items-center gap-2 text-sm leading-snug">
                      <input
                        type="checkbox"
                        className="shrink-0"
                        data-testid="thesis"
                        checked={thesis}
                        onChange={(e) => {
                          const checked = e.target.checked;
                          setThesis(checked);
                          // TODO(legal-review): auto-submit for real accounts — paper executes immediately after ack.
                          if (checked && autoSubmitOnAck && !order.isPending) {
                            order.mutate();
                          }
                        }}
                      />
                      <span>
                        I accept the thesis and have reviewed each options leg, contract quantity, estimated premium, and
                        account impact.
                      </span>
                    </label>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <p>Contracts per leg</p>
                      <p>
                        <input
                          className="w-20 bg-ink"
                          type="number"
                          min={1}
                          value={contractsPerLeg}
                          onChange={(e) => setContractsPerLeg(Math.max(1, Number(e.target.value)))}
                          data-testid="contracts-per-leg"
                        />
                      </p>
                      <p>Type</p>
                      <p className="font-mono text-champagne/90" data-testid="order-type">
                        {orderTypeLabel}
                      </p>
                    </div>
                    {requiresPlaceOrder ? (
                      <button
                        data-testid="submit-order"
                        disabled={!thesis || order.isPending}
                        onClick={() => order.mutate()}
                        className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
                      >
                        Place order
                      </button>
                    ) : (
                      <p className="text-sm text-champagne/70" data-testid="auto-exec-hint">
                        Composite ≥{scanAutoThreshold} — acknowledging the thesis will auto-submit these options
                        legs.
                      </p>
                    )}
                    {msg && <p className="text-sm">{msg}</p>}
                  </>
                )}
              </div>
            )}
          </motion.section>
        </AnimatePresence>
      )}

      {orderConfirmation ? (
        <OrderConfirmationCertificate
          details={orderConfirmation}
          onDismiss={() => {
            setOrderConfirmation(null);
            nav("/app");
          }}
        />
      ) : null}
    </main>
  );
}

function ScanIntro({ symbol }: { symbol: string }) {
  return (
    <main className="scan-intro" data-testid="scan-intro">
      <div className="scan-mesh" aria-hidden />
      <div className="scan-beam scan-beam-h" aria-hidden />
      <div className="scan-beam scan-beam-v" aria-hidden />
      <div className="scan-intro-stack">
        <div className="scan-target" aria-hidden>
          <span className="scan-target-pulse" />
          <svg className="scan-target-svg" viewBox="0 0 120 120">
            <circle className="scan-target-outer" cx="60" cy="60" r="46" />
            <circle className="scan-target-inner" cx="60" cy="60" r="9" />
            <circle className="scan-target-dot" cx="60" cy="60" r="2.15" />
            <path className="scan-target-ticks" d="M60 14v16M106 60H90M60 106V90M14 60h16" />
          </svg>
        </div>
        <motion.p
          className="scan-ticker"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.12 }}
          data-testid="scan-ticker"
        >
          {symbol}
        </motion.p>
        <motion.p
          className="scan-status"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.32 }}
        >
          Initializing multi-layer analysis
        </motion.p>
        <div className="scan-progress" role="progressbar" aria-label="Initializing multi-layer analysis">
          <span className="scan-progress-fill" />
        </div>
      </div>
    </main>
  );
}
