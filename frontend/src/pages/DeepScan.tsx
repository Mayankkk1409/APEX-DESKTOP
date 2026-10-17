import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ApexScoreScan } from "../components/ApexScoreScan";
import { ApexWordmark } from "../components/ApexWordmark";
import { FundamentalsScan } from "../components/FundamentalsScan";
import { OptionsChainGreeks } from "../components/OptionsChainGreeks";
import { OrderConfirmationCertificate } from "../components/OrderConfirmationCertificate";
import { OrderRefusalDialog } from "../components/OrderRefusalDialog";
import { OrderSubmitProgress, type OrderProgressFacts, type OrderProgressPhase } from "../components/OrderSubmitProgress";
import { RiskReviewLegs } from "../components/RiskReviewLegs";
import { RiskReviewOrderActions } from "../components/RiskReviewOrderActions";
import { prepareEquitySentiment, SentimentScan } from "../components/SentimentScan";
import { StrategyScan } from "../components/StrategyScan";
import { EquityResearch } from "../components/EquityResearch";
import { ResearchModeToggle } from "../components/ResearchModeToggle";
import { TaSnapshot } from "../components/TaSnapshot";
import { VolatilityScan } from "../components/volatility/VolatilityScan";
import { CAROUSEL_LAYERS, EQUITY_SLIDE_LAYERS, SCAN_SLIDE_LAYERS, SNAPSHOT_STUDIES } from "../constants";
import { scoreTier } from "../lib/chartHighlight";
import { orientShareLevels } from "../lib/equityLevels";
import { optionReviewRows, optionsLegBlockReason } from "../lib/orderTicket";
import { explainOrderRefusal } from "../lib/orderRefusal";
import { blockedEligibilityLine, orderPlacement, overrideReasonText, thesisCheckboxState } from "../lib/riskReview";
import { compositeBelowMinimum } from "../lib/scoreFormat";
import { normalizeStrategyName } from "../lib/strategyDisplay";
import { RESEARCH_REVEAL_MS, RESEARCH_WASH_MS } from "../lib/researchMode";
import { readUserSettings } from "../lib/userSettings";
import { applyReturnedFillBalances, applyReturnedOrderRows, refreshDeskQueries } from "../lib/deskRefresh";
import { buildOrderConfirmationDetails } from "../lib/orderFormat";
import type { OhlcBar } from "../lib/ta";
import { useBrokerage } from "../hooks/useBrokerage";
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

type DeepScanTestBoot = {
  skipIntro: boolean;
  initialIndex: number;
  invokeScan: boolean;
};

const idleDeepScanTestBoot = (): DeepScanTestBoot => ({
  skipIntro: false,
  initialIndex: 0,
  invokeScan: false,
});

let deepScanTestBoot: DeepScanTestBoot = idleDeepScanTestBoot();

/** Static markup tests skip the intro splash and can open a slide. Production leaves this idle. */
export function setDeepScanTestBoot(patch: Partial<DeepScanTestBoot>) {
  deepScanTestBoot = { ...deepScanTestBoot, ...patch };
}

export function resetDeepScanTestBoot() {
  deepScanTestBoot = idleDeepScanTestBoot();
}

function slideLayers(reported: readonly string[] | undefined): string[] {
  const all = reported ?? [];
  if (!all.length) return [...SCAN_SLIDE_LAYERS];
  return SCAN_SLIDE_LAYERS.filter((name) => all.includes(name));
}

export function DeepScan() {
  const nav = useNavigate();
  const loc = useLocation();
  const reopenScanId = (loc.state as { reopenScanId?: string } | null)?.reopenScanId ?? "";
  const qc = useQueryClient();
  const hooked = useSession();
  // Static markup reads getState(); the browser hook snapshot is the initial store
  // value under renderToStaticMarkup, so a test's setState would otherwise be ignored.
  const live = typeof window === "undefined" ? useSession.getState() : hooked;
  const symbol = live.symbol;
  const timeframe = live.timeframe;
  const expiry = live.expiry;
  const snapshot = live.snapshot;
  const chartImage = live.chartImage;
  const chartImageFrozen = live.chartImageFrozen;
  const capturedBars = live.capturedBars;
  const capturedContext = live.capturedContext;
  const capturedDaily = live.capturedDaily;
  const captureSnapshot = live.captureSnapshot;
  const setRecommendedContract = live.setRecommendedContract;
  const user = live.user;
  const accountMode = live.accountMode;
  const brokerage = useBrokerage();
  const testBoot = deepScanTestBoot;
  const [intro, setIntro] = useState(() => !testBoot.skipIntro);
  const [idx, setIdx] = useState(() => testBoot.initialIndex);
  const [thesis, setThesis] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [spreadConfirmed, setSpreadConfirmed] = useState(false);
  const [contractsPerLeg, setContractsPerLeg] = useState(1);
  const [sharesText, setSharesText] = useState("1");
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const sharesQty = /^\d+$/.test(sharesText.trim()) ? Number(sharesText) : 0;
  const [reduceMotion, setReduceMotion] = useState(false);
  const [exitGuardOpen, setExitGuardOpen] = useState(false);
  const [protectExits, setProtectExits] = useState(false);
  const [msg, setMsg] = useState("");
  const [orderRefusal, setOrderRefusal] = useState<string | null>(null);
  const [orderConfirmation, setOrderConfirmation] = useState<OrderConfirmationDetails | null>(null);
  const [progressComplete, setProgressComplete] = useState(false);
  const [submitPhase, setSubmitPhase] = useState<OrderProgressPhase>("submitting");
  const [submitFacts, setSubmitFacts] = useState<OrderProgressFacts | null>(null);
  const filledOutcome = useRef<OrderConfirmationDetails | null>(null);
  const filledResult = useRef<OrderPlacementResult | null>(null);
  const submitLock = useRef(false);

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

  const researchMode = useSession((s) => s.researchMode);
  const equityMode = researchMode === "equity";
  const scanExpiry = expiry || undefined;
  const scanKey = equityMode
    ? (["scan", "equity", locked.captured_at, locked.symbol, locked.timeframe] as const)
    : reopenScanId
      ? (["scan-reopen", reopenScanId] as const)
      : (["scan", locked.captured_at, locked.symbol, locked.timeframe, expiry] as const);
  const scanQueryFn = () =>
    (equityMode
      ? api.scan(locked, undefined, "equity")
      : reopenScanId
        ? api.scanById(reopenScanId)
        : api.scan(locked, scanExpiry)) as Promise<ScanResult>;
  const scan = useQuery({
    queryKey: scanKey,
    queryFn: scanQueryFn,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });
  const scanInvoked = useRef(false);
  if (testBoot.invokeScan && !scanInvoked.current) {
    scanInvoked.current = true;
    void qc.fetchQuery({ queryKey: scanKey, queryFn: scanQueryFn }).catch(() => undefined);
  }

  const expiries = useQuery({
    queryKey: ["exp", symbol],
    queryFn: () => api.expirations(symbol),
    enabled: Boolean(symbol) && !reopenScanId,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (reopenScanId) return;
    const list = expiries.data?.expirations ?? [];
    if (!list.length || expiry) return;
    useSession.getState().setExpiry(list[0].date);
  }, [expiries.data, expiry, reopenScanId]);

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
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduceMotion(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
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
        defined_risk?: boolean;
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
          order_type?: string;
          price?: number | null;
          limit_basis?: string | null;
        }>;
        contracts_per_leg?: number;
        equity_legs?: Array<{
          symbol: string;
          side: string;
          qty?: number;
          position_intent?: string;
          order_type?: string;
          price?: number | null;
        }>;
        equity_note?: string | null;
        equity_required?: boolean;
        block_reason?: string | null;
        auto_execute_eligible?: boolean;
        auto_exec_line?: string | null;
        executable?: boolean;
        placeable?: boolean;
        spread_confirmation_required?: boolean;
        spread_block_reasons?: string[];
        quote_not_current?: boolean;
        quote_as_of?: string | null;
        structure_label?: string | null;
        stock_legs?: Array<{
          symbol: string;
          side: string;
          qty?: number;
          already_held?: boolean;
          note?: string | null;
          price?: number | null;
        }>;
      }
    | undefined;
  const scanAutoThreshold = riskReview?.auto_execution_threshold ?? autoExecMinScore;
  const executionTier = riskReview?.execution_tier ?? scoreTier(compositeScore, scanAutoThreshold);
  const strategyLegs = riskReview?.strategy_legs ?? [];
  const equityLegs = riskReview?.equity_legs ?? [];
  const equityNote = riskReview?.equity_note ?? null;
  const definedRisk = riskReview?.defined_risk ?? Boolean(riskReview?.auto_submit_on_ack);
  const strategyLayerData = scan.data?.layer_data?.strategy as StrategyLayer | undefined;
  const displayedComposite =
    typeof strategyLayerData?.composite_score === "number" ? strategyLayerData.composite_score : compositeScore;
  const strategyName = strategyLayerData?.structure_label || riskReview?.structure_label || strategyLayerData?.selected_strategy || "";
  const reviewRows = useMemo(
    () =>
      optionReviewRows({
        ticketLegs: strategyLegs,
        metricLegs: strategyLayerData?.metrics?.legs,
        strategyName,
        equityRequired: riskReview?.equity_required,
        equityLegs,
        equityCovered: strategyLayerData?.metrics?.equity_covered_by_holdings,
        validationError: strategyLayerData?.metrics?.validation_error,
        multiplier: strategyLayerData?.metrics?.per_contract_multiplier,
        contractsPerLeg,
      }),
    [contractsPerLeg, equityLegs, riskReview?.equity_required, strategyLayerData, strategyLegs, strategyName],
  );
  const emptyLegReason = optionsLegBlockReason({
    blockReason: riskReview?.block_reason,
    equityNote,
    validationError: strategyLayerData?.metrics?.validation_error,
    validationErrors: strategyLayerData?.validation_errors,
    riskNotes: strategyLayerData?.risk_notes,
  });
  // The browser auto-exec toggle defaults off and is not stored on the server, so it is not a gate.
  const storedEligibility = riskReview?.auto_exec_line || strategyLayerData?.auto_exec_line || null;
  const eligibilityLine =
    storedEligibility &&
    /Auto-execute eligible/.test(storedEligibility) &&
    displayedComposite != null &&
    compositeBelowMinimum(displayedComposite, scanAutoThreshold)
      ? blockedEligibilityLine(displayedComposite, scanAutoThreshold, "composite is below your minimum")
      : storedEligibility;
  const structureExecutable = riskReview?.executable === true;
  const structurePlaceable = riskReview?.placeable !== false;
  const hardBlocked = (strategyLayerData?.hard_block_reasons ?? []).some((note) => note.trim().length > 0);
  const placement = orderPlacement({
    serverAutoSubmit: riskReview?.auto_execute_eligible === true,
    composite: displayedComposite,
    threshold: scanAutoThreshold,
    definedRisk,
    hasLegs: reviewRows.length > 0 || (riskReview?.stock_legs?.length ?? 0) > 0,
    executable: structureExecutable,
    validationPassed: structurePlaceable,
    placeable: riskReview?.placeable,
    spreadConfirmationRequired: riskReview?.spread_confirmation_required === true,
    spreadConfirmed,
    blockReason: eligibilityLine || riskReview?.block_reason || null,
    hardBlocked,
    readOnly: brokerage.usingBrokerage,
  });
  // One checkbox: it submits at or above the saved minimum when the server says
  // the structure is executable, and it stays off when the server will refuse.
  const thesisState = thesisCheckboxState(placement);
  const equityRaw = (equityMode ? scan.data?.layer_data?.equity : undefined) as
    | {
        action?: string;
        why?: string;
        levels?: { entry?: number | null; stop?: number | null; take_profit?: number | null };
        trend?: string;
        holds_shares?: boolean;
        market?: { price?: number | null; atr?: number | null; support?: number | null; resistance?: number | null };
        scorecard?: {
          bull?: { earned?: number; possible?: number; passes?: boolean };
          bear?: { earned?: number; possible?: number; passes?: boolean };
        };
        scores?: { overall?: number | null };
      }
    | undefined;
  const equityPlan = equityRaw
    ? { ...equityRaw, levels: orientShareLevels(equityRaw) }
    : undefined;
  const downsideOrder =
    equityPlan?.action === "Avoid" &&
    typeof equityPlan.levels?.entry === "number" &&
    typeof equityPlan.levels?.stop === "number" &&
    typeof equityPlan.levels?.take_profit === "number" &&
    equityPlan.levels.stop > equityPlan.levels.entry &&
    equityPlan.levels.take_profit < equityPlan.levels.entry;
  const equityTradable = equityPlan?.action === "Buy" || equityPlan?.action === "Sell" || downsideOrder;
  const equityScore = typeof equityPlan?.scores?.overall === "number" ? equityPlan.scores.overall : null;
  const equityPlacement = orderPlacement({
    serverAutoSubmit: false,
    composite: equityScore,
    threshold: scanAutoThreshold,
    definedRisk: true,
    hasLegs: equityTradable && sharesQty >= 1 && typeof equityPlan?.levels?.entry === "number",
    executable: equityTradable,
    validationPassed: equityTradable,
    placeable: equityTradable,
    blockReason: equityTradable ? null : equityPlan?.why || "This equity research has no share order to send.",
    hardBlocked: !equityTradable,
    readOnly: brokerage.usingBrokerage,
  });
  const equityThesis = thesisCheckboxState(equityPlacement);
  const equitySentiment = useMemo(() => {
    const raw = scan.data?.layer_data?.sentiment as SentimentLayer | undefined;
    if (!raw?.components?.news) return undefined;
    return prepareEquitySentiment(raw);
  }, [scan.data]);
  const orderTypeLabel = reviewRows.length
    ? reviewRows
        .map((leg) =>
          leg.price != null ? `${leg.orderTypeLabel} ${leg.price.toFixed(2)}` : leg.orderTypeLabel,
        )
        .join(" · ")
    : "limit";
  const chainStrategyHighlight = useMemo(() => {
    if (!scan.data) return undefined;
    const metricLegs = (strategyLayerData?.metrics?.legs ?? []).filter(
      (leg) => leg.side === "call" || leg.side === "put",
    );
    const riskLegs = (riskReview?.strategy_legs ?? []).map((leg) => ({
      side: leg.option_side,
      option_side: leg.option_side,
      strike: leg.strike,
      expiry: leg.expiry,
      symbol: leg.symbol,
    }));
    const chainRecommended = (
      scan.data.layer_data?.options_chain_greeks as { recommendedContract?: ChainAnalysis["recommendedContract"] } | undefined
    )?.recommendedContract;
    return {
      legs: metricLegs.length ? metricLegs : riskLegs,
      recommended:
        strategyLayerData?.recommended_contract ?? scan.data.recommendedContract ?? chainRecommended ?? null,
    };
  }, [riskReview?.strategy_legs, scan.data, strategyLayerData]);

  function confirmationFromResult(result: OrderPlacementResult): OrderConfirmationDetails {
    return buildOrderConfirmationDetails(result, {
      strategyName,
      ticker: locked.symbol,
      user,
      accountMode,
      orderAssetClass: equityMode ? "us_equity" : "us_option",
    });
  }

  const layers = useMemo(
    () => (equityMode ? [...EQUITY_SLIDE_LAYERS] : slideLayers(scan.data?.layers)),
    [equityMode, scan.data?.layers],
  );
  const modeSeen = useRef(researchMode);
  const [modeWash, setModeWash] = useState(0);
  const [modePhase, setModePhase] = useState<"idle" | "changing">("idle");
  useEffect(() => {
    if (modeSeen.current === researchMode) return;
    modeSeen.current = researchMode;
    setIdx(0);
    if (reduceMotion) return;
    setModeWash((n) => n + 1);
    setModePhase("changing");
    document.documentElement.dataset.researchTransition = researchMode;
    const done = window.setTimeout(() => {
      setModePhase("idle");
      delete document.documentElement.dataset.researchTransition;
    }, RESEARCH_WASH_MS[researchMode] + RESEARCH_REVEAL_MS + 120);
    return () => {
      window.clearTimeout(done);
      delete document.documentElement.dataset.researchTransition;
    };
  }, [researchMode, reduceMotion]);
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
  const slideExpiry = expiry;
  const riskLayer = current === "risk_review";
  // Full-width slides that run their own card carousel and own the arrow keys.
  const ownsArrows =
    !layers.length || CAROUSEL_LAYERS.includes(current ?? "") || (equityMode && current === "equity_technical");
  const fullWidth =
    equityMode || technical || chainLayer || volLayer || sentimentLayer || fundamentalsLayer || apexScoreLayer || strategyLayer;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as { closest?: (selector: string) => unknown } | null;
      if (ownsArrows && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") setIdx((i) => Math.min(i + 1, Math.max(layers.length - 1, 0)));
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") setIdx((i) => Math.max(i - 1, 0));
      if (e.key === "Home") setIdx(0);
      if (e.key === "End") setIdx(Math.max(layers.length - 1, 0));
      if (e.key === "Escape") {
        if (orderRefusal !== null) return;
        nav("/app");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [layers.length, nav, ownsArrows, orderRefusal]);

  function orderProgressFacts(detail?: string): OrderProgressFacts {
    const strategy = normalizeStrategyName(strategyName);
    return {
      ticker: locked.symbol || undefined,
      strategy: strategyName.trim() ? strategy : undefined,
      detail,
    };
  }

  const overrideReasons = overrideReasonText([
    riskReview?.quote_not_current
      ? `Quote not current${riskReview.quote_as_of ? `. Quoted ${riskReview.quote_as_of}` : ""}`
      : null,
    ...(riskReview?.spread_block_reasons ?? []),
    riskReview?.block_reason,
    eligibilityLine?.includes("Not auto-executable:")
      ? eligibilityLine.split("Not auto-executable:")[1]
      : null,
  ]);
  const order = useMutation({
    // The accepted thesis travels with the submit so the checkbox click does not
    // race React state. An explicit override is the only path past a failed check.
    mutationFn: (input: { thesisAccepted: boolean; userOverride?: boolean; protectExits?: boolean }) => {
      if (useSession.getState().researchMode === "equity") {
        const plan = scan.data?.layer_data?.equity as
          | {
              action?: string;
              why?: string;
              levels?: { entry?: number | null; stop?: number | null; take_profit?: number | null };
              trend?: string;
              holds_shares?: boolean;
              market?: { price?: number | null; atr?: number | null; support?: number | null; resistance?: number | null };
              scorecard?: {
                bull?: { earned?: number; possible?: number; passes?: boolean };
                bear?: { earned?: number; possible?: number; passes?: boolean };
              };
            }
          | undefined;
        const downside =
          plan?.action === "Avoid" &&
          typeof plan.levels?.stop === "number" &&
          typeof plan.levels?.entry === "number" &&
          typeof plan.levels?.take_profit === "number" &&
          plan.levels.stop > plan.levels.entry &&
          plan.levels.take_profit < plan.levels.entry;
        if (plan?.action !== "Buy" && plan?.action !== "Sell" && !downside) {
          throw new Error(plan?.why || "This equity research has no share order to send.");
        }
        if (!Number.isInteger(sharesQty) || sharesQty < 1 || sharesQty > 1_000_000) {
          throw new Error("Quantity must be a whole number from 1 to 1,000,000. Fractions, zero, and negative sizes are not sent.");
        }
        const shareLevels = orientShareLevels(plan);
        const limit = shareLevels.entry;
        if (typeof limit !== "number" || limit <= 0) {
          throw new Error("This equity plan has no entry price, so no order was sent.");
        }
        const userOverride = input.userOverride === true;
        return api.order({
          scan_id: scan.data?.id,
          thesis_accepted: input.thesisAccepted,
          asset_class: "us_equity",
          symbol: locked.symbol,
          side: plan.action === "Sell" || downside ? "sell" : "buy",
          qty: sharesQty,
          order_type: "limit",
          limit_price: limit,
          protect_exits: input.protectExits === true,
          stop_price: shareLevels.stop,
          take_profit_price: shareLevels.take_profit,
          user_override: userOverride,
          override_reasons: userOverride ? [overrideReasons] : [],
          confirm_duplicate: allowDuplicate,
          data_source: brokerage.usingBrokerage ? "brokerage" : "paper",
        });
      }
      if (!reviewRows.length) {
        throw new Error(emptyLegReason);
      }
      const userOverride = input.userOverride === true;
      return api.order({
        scan_id: scan.data?.id,
        thesis_accepted: input.thesisAccepted,
        asset_class: "us_option",
        legs: reviewRows.map((leg) => ({
          symbol: leg.symbol,
          side: leg.side,
          qty: leg.contracts,
          strike: leg.strike,
          option_side: leg.optionSide,
          expiry: leg.expiry,
          price: leg.price,
          order_type: "limit",
          limit_price: leg.price,
        })),
        contracts_per_leg: contractsPerLeg,
        confirm_duplicate: allowDuplicate,
        spread_confirmed: spreadConfirmed,
        user_override: userOverride,
        override_reasons: userOverride ? [overrideReasons] : [],
        data_source: brokerage.usingBrokerage ? "brokerage" : "paper",
      });
    },
    onSuccess: (r) => {
      setThesis(false);
      setAllowDuplicate(false);
      const result = r as OrderPlacementResult;
      const status = (result.status || "").toLowerCase();
      if (status === "accepted" || status === "pending" || status === "new") {
        const sentence =
          result.status_message ||
          "Your order is waiting to fill at the broker. You can follow its status in Pending orders.";
        filledOutcome.current = null;
        filledResult.current = null;
        setOrderConfirmation(null);
        setOrderRefusal(sentence);
        setSubmitPhase("recorded");
        setSubmitFacts(orderProgressFacts("Sent to the broker."));
        setProgressComplete(true);
        void qc.invalidateQueries({ queryKey: ["orders"] });
        return;
      }
      if (status === "unknown") {
        const sentence =
          result.status_message ||
          "The broker result is not confirmed. This order may already have been sent. Check Portfolio before you try again. APEX will not send a second copy from this attempt.";
        filledOutcome.current = null;
        filledResult.current = null;
        setOrderConfirmation(null);
        setOrderRefusal(sentence);
        setSubmitPhase("not-submitted");
        setSubmitFacts(orderProgressFacts(sentence));
        setProgressComplete(true);
        void qc.invalidateQueries({ queryKey: ["orders"] });
        return;
      }
      if (status === "queued") {
        const sentence =
          result.queue_message ||
          "A current price is unavailable. Your order is waiting and will be submitted automatically when the market permits trading and a valid price is available, provided it still meets your confirmed order terms. You can cancel it before submission.";
        filledOutcome.current = null;
        filledResult.current = null;
        setOrderConfirmation(null);
        setOrderRefusal(sentence);
        setSubmitPhase("queued");
        setSubmitFacts(orderProgressFacts("Saved to the queue. It has not been filled."));
        setProgressComplete(true);
        void qc.invalidateQueries({ queryKey: ["orders"] });
        return;
      }
      if (status !== "filled") {
        const sentence = explainOrderRefusal(
          result.status ? `Order status: ${result.status}` : "The order was not filled.",
        );
        filledOutcome.current = null;
        filledResult.current = null;
        setOrderConfirmation(null);
        setOrderRefusal(sentence);
        setSubmitPhase("not-submitted");
        setSubmitFacts(orderProgressFacts(sentence));
        setProgressComplete(true);
        return;
      }
      filledResult.current = result;
      filledOutcome.current = confirmationFromResult(result);
      setOrderRefusal(null);
      setSubmitPhase("recorded");
      setSubmitFacts(orderProgressFacts());
      setProgressComplete(true);
    },
    onMutate: () => {
      submitLock.current = true;
      setMsg("");
      setOrderRefusal(null);
      setOrderConfirmation(null);
      setProgressComplete(false);
      setSubmitPhase("submitting");
      setSubmitFacts(orderProgressFacts("Checking the order, then sending it."));
      filledOutcome.current = null;
      filledResult.current = null;
    },
    onError: (e) => {
      const sentence = explainOrderRefusal((e as Error).message);
      setThesis(false);
      if (/identical order/i.test(sentence)) setAllowDuplicate(true);
      filledOutcome.current = null;
      filledResult.current = null;
      setOrderConfirmation(null);
      setOrderRefusal(sentence);
      setSubmitPhase("not-submitted");
      setSubmitFacts(orderProgressFacts(sentence));
      setProgressComplete(true);
    },
  });

  function finishOrderProgress() {
    const details = filledOutcome.current;
    const result = filledResult.current;
    if (details && result) {
      setOrderConfirmation(details);
      applyReturnedFillBalances(qc, result);
      applyReturnedOrderRows(qc, result);
      refreshDeskQueries(qc);
    }
    filledOutcome.current = null;
    filledResult.current = null;
    submitLock.current = false;
    setProgressComplete(false);
  }

  if (intro) {
    return <ScanIntro symbol={locked.symbol} />;
  }

  return (
    <main
      className={`min-h-screen px-6 py-6 ${fullWidth ? "max-w-none" : ""}${modePhase === "idle" ? "" : ` is-mode-${modePhase}`}`}
      data-testid="deep-scan"
      data-research-mode={researchMode}
      data-layers={layers.join(",")}
    >
      {modeWash > 0 ? <div key={modeWash} className="research-mode-wash" data-mode={researchMode} aria-hidden="true" /> : null}
      <div className="research-mode-sheet">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ApexWordmark />
          <button className="text-sm text-bronze" onClick={() => nav("/app")}>
            ← Dashboard
          </button>
          <ResearchModeToggle testId="research-mode-scan" />
        </div>
        <p className="font-mono text-xs text-bronze" data-testid="snapshot-header">
          Snapshot {locked.symbol} · {locked.timeframe}
          {!equityMode && expiry ? ` · expiry ${expiry}` : ""} · {plotBars.length} bars · {windowFrom.slice(0, 10)} → {windowTo.slice(0, 10)} ·{" "}
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

      <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={researchMode}
        className="research-mode-stage"
        data-testid="research-mode-stage"
        data-mode={researchMode}
        initial={false}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 1, x: 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
      {equityMode ? (
        scan.isFetching || scan.data?.research_mode !== "equity" ? (
          <p className="mt-8 text-sm text-faint" data-testid="equity-loading">
            Preparing the equity research…
          </p>
        ) : current === "equity_technical" ? (
          <div>
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
            <EquityResearch slide={current} plan={scan.data.layer_data.equity as never} />
          </div>
        ) : current === "equity_sentiment" ? (
          <section className="mt-4" data-testid="sentiment-layer">
            <SentimentScan symbol={locked.symbol} expiry="" focus="equity" initial={equitySentiment} />
          </section>
        ) : current === "equity_fundamentals" ? (
          <section className="mt-4" data-testid="fundamentals-layer">
            <FundamentalsScan
              symbol={locked.symbol}
              equityDetail
              initial={scan.data.layer_data.fundamentals as FundamentalsLayer}
            />
          </section>
        ) : (
          <>
            <EquityResearch slide={current} plan={scan.data.layer_data.equity as never} />
            {current === "equity_plan" ? (
              <div className="mx-auto mt-6 max-w-4xl rounded-2xl border border-line bg-panel p-6" data-testid="equity-order">
                <h1 className="font-display text-3xl">Risk review</h1>
                <p className="mt-4 text-sm text-champagne/70" data-testid="order-composition">
                  {equityTradable
                    ? `Share order — ${equityPlan?.action} ${sharesQty} ${locked.symbol} at the entry limit.`
                    : equityPlan?.why || "This equity research has no share order to send."}
                </p>
                <div className="mt-6 space-y-4">
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <p>Shares</p>
                    <p>
                      <input
                        className="w-20 bg-ink"
                        type="text"
                        inputMode="numeric"
                        value={sharesText}
                        data-testid="shares-qty"
                        onChange={(e) => {
                          setSharesText(e.target.value);
                          setThesis(false);
                          setAllowDuplicate(false);
                        }}
                      />
                    </p>
                    {sharesQty < 1 ? (
                      <p className="col-span-2 text-sm text-champagne/80" data-testid="qty-error">
                        Quantity must be a whole number from 1 to 1,000,000. A negative or fractional size is not sent.
                      </p>
                    ) : null}
                    <p>Type</p>
                    <p className="font-mono text-champagne/90" data-testid="order-type">
                      {typeof equityPlan?.levels?.entry === "number"
                        ? `Limit ${equityPlan.levels.entry.toFixed(2)}`
                        : "Limit unavailable"}
                    </p>
                  </div>
                  <RiskReviewOrderActions
                    placement={equityPlacement}
                    pending={order.isPending}
                    acceptanceText="I accept the thesis and have reviewed the share quantity, entry, stop, take profit, and account impact."
                    thesisAccepted={thesis}
                    onThesisChange={(checked) => {
                      setThesis(checked);
                      if (!checked || order.isPending || submitLock.current) return;
                      if (equityThesis.submitsOnAccept && !equityPlacement.overrideRequired) {
                        setMsg("");
                        setOrderRefusal(null);
                        order.mutate({ thesisAccepted: true });
                      } else if (equityPlacement.overrideRequired) {
                        setOverrideOpen(true);
                      }
                    }}
                    onPlace={() => {
                      if (submitLock.current || order.isPending) return;
                      if (!thesis) {
                        setMsg("Accept the thesis to place this trade.");
                        return;
                      }
                      setProtectExits(false);
                      setExitGuardOpen(true);
                    }}
                  />
                  {!equityPlacement.placeTradeEnabled && !equityPlacement.acknowledgeEnabled ? (
                    <button
                      type="button"
                      disabled
                      data-testid="submit-order"
                      className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
                    >
                      Place Trade
                    </button>
                  ) : null}
                  {msg && <p className="text-sm">{msg}</p>}
                </div>
              </div>
            ) : null}
          </>
        )
      ) : technical ? (
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
            strategyHighlight={chainStrategyHighlight}
          />
        </section>
      ) : volLayer ? (
        <section className="mt-4" data-testid="volatility-scan-layer">
          <VolatilityScan
            symbol={locked.symbol}
            expiry={slideExpiry}
            initial={data as unknown as VolatilitySnapshot | undefined}
          />
        </section>
      ) : sentimentLayer ? (
        <section className="mt-4" data-testid="sentiment-layer">
          <SentimentScan
            symbol={locked.symbol}
            expiry={slideExpiry}
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
                {reviewRows.length === 0 ? (
                  <p className="text-sm text-champagne/80" data-testid="risk-blocked">
                    {emptyLegReason}
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-champagne/70" data-testid="order-composition">
                      {equityLegs.length
                        ? "The stock leg is submitted with the option legs. Shares fill before any short call."
                        : equityNote
                          ? equityNote
                          : `Options execution — ${reviewRows.length} leg${reviewRows.length === 1 ? "" : "s"} from the recommended strategy.`}
                    </p>
                    {equityNote && equityLegs.length ? (
                      <p className="text-sm text-champagne/80" data-testid="equity-order-note">
                        {equityNote}
                      </p>
                    ) : null}
                    {equityLegs.length ? (
                      <ul className="space-y-2 text-sm" data-testid="equity-legs-review">
                        {equityLegs.map((leg) => (
                          <li key={`stock-${leg.symbol}`} className="rounded border border-line/60 px-3 py-2 font-mono text-xs">
                            {leg.position_intent === "sell_short" ? "SELL SHORT" : leg.side.toUpperCase()} {leg.qty} {leg.symbol}{" "}
                            stock · {leg.order_type ?? "market"}
                            {leg.price != null ? ` @ $${Number(leg.price).toFixed(2)}` : ""}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    <RiskReviewLegs rows={reviewRows} />
                    {riskReview?.stock_legs?.length ? (
                      <ul className="space-y-2 text-sm" data-testid="stock-leg-context">
                        {riskReview.stock_legs.map((leg) => (
                          <li key={`held-${leg.symbol}`} className="rounded border border-line/60 px-3 py-2 font-mono text-xs">
                            {leg.qty} {leg.symbol} shares
                            {leg.note ? ` · ${leg.note}` : ""}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {eligibilityLine && eligibilityLine !== thesisState.reason ? (
                      <p id="auto-exec-eligibility" className="text-sm text-champagne/80" data-testid="auto-exec-eligibility">
                        {eligibilityLine}
                      </p>
                    ) : null}
                    {riskReview?.quote_not_current ? (
                      <p className="text-sm text-champagne/80" data-testid="quote-not-current">
                        Quote not current{riskReview.quote_as_of ? `. Quoted ${riskReview.quote_as_of}` : ""}.
                      </p>
                    ) : null}
                    {riskReview?.spread_confirmation_required ? (
                      <label className="flex cursor-pointer items-center gap-2 text-sm leading-snug">
                        <input
                          type="checkbox"
                          data-testid="spread-confirm"
                          checked={spreadConfirmed}
                          onChange={(e) => setSpreadConfirmed(e.target.checked)}
                        />
                        <span>{(riskReview.spread_block_reasons ?? []).join(" ") || eligibilityLine}</span>
                      </label>
                    ) : null}
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <p>Contracts per leg</p>
                      <p>
                        <input
                          className="w-20 bg-ink"
                          type="number"
                          min={1}
                          value={contractsPerLeg}
                          onChange={(e) => {
                            const raw = e.target.value.trim();
                            setThesis(false);
                            setAllowDuplicate(false);
                            if (!/^\d+$/.test(raw)) {
                              setContractsPerLeg(0);
                              return;
                            }
                            const next = Number(raw);
                            setContractsPerLeg(next >= 1 && next <= 1_000_000 ? next : 0);
                          }}
                          data-testid="contracts-per-leg"
                        />
                      </p>
                      <p>Type</p>
                      <p className="font-mono text-champagne/90" data-testid="order-type">
                        {orderTypeLabel}
                      </p>
                    </div>
                    <RiskReviewOrderActions
                      placement={placement}
                      pending={order.isPending}
                      thesisAccepted={thesis}
                      onThesisChange={(checked) => {
                        setThesis(checked);
                        if (!checked || order.isPending || submitLock.current) return;
                        if (thesisState.submitsOnAccept && !placement.overrideRequired) {
                          setMsg("");
                          setOrderRefusal(null);
                          order.mutate({ thesisAccepted: true });
                          return;
                        }
                        if (placement.overrideRequired) {
                          setOverrideOpen(true);
                          return;
                        }
                        if (!placement.placeTradeEnabled) {
                          const sentence =
                            (strategyLayerData?.hard_block_reasons ?? []).find((note) => note.trim()) ||
                            placement.note ||
                            "This order was not submitted.";
                          setMsg("");
                          setOrderRefusal(sentence);
                          setSubmitPhase("not-submitted");
                          setSubmitFacts(orderProgressFacts(sentence));
                          setProgressComplete(true);
                        }
                      }}
                      onPlace={() => {
                        if (submitLock.current || order.isPending) return;
                        if (!thesis) {
                          setMsg("Accept the thesis to place this trade.");
                          return;
                        }
                        if (placement.overrideRequired) {
                          setOverrideOpen(true);
                          return;
                        }
                        order.mutate({ thesisAccepted: true });
                      }}
                    />
                    {msg && <p className="text-sm">{msg}</p>}
                  </>
                )}
              </div>
            )}
          </motion.section>
        </AnimatePresence>
      )}
      </motion.div>
      </AnimatePresence>

      {exitGuardOpen ? (
        <div
          className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="exit-guard-title"
          data-testid="exit-guard"
        >
          <div className="order-cert-card w-full max-w-lg">
            <div className="order-cert-frame">
              <div className="order-cert-inner order-cert-stack">
                <h2 id="exit-guard-title" className="order-cert-title">Place share order</h2>
                <p className="order-cert-copy">
                  {equityPlacement.overrideRequired
                    ? `Not recommended. ${overrideReasons}. This does not send the order until you confirm.`
                    : "The order is sent only after you confirm. Automatic exit protection stays off unless you check it."}
                </p>
                <label className="flex cursor-pointer items-start gap-2 text-sm leading-snug">
                  <input
                    type="checkbox"
                    data-testid="exit-guard-check"
                    checked={protectExits}
                    onChange={(e) => setProtectExits(e.target.checked)}
                  />
                  <span>
                    Automatically close this position if the stop
                    {typeof equityPlan?.levels?.stop === "number" ? ` (${equityPlan.levels.stop.toFixed(2)})` : ""}
                    {" "}or the take-profit
                    {typeof equityPlan?.levels?.take_profit === "number" ? ` (${equityPlan.levels.take_profit.toFixed(2)})` : ""}
                    {" "}is reached.
                  </span>
                </label>
                <div className="order-cert-actions">
                  <button type="button" className="order-cert-dismiss order-cert-dismiss-secondary" data-testid="exit-guard-cancel" onClick={() => setExitGuardOpen(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="order-cert-dismiss"
                    data-testid="exit-guard-place"
                    disabled={order.isPending}
                    onClick={() => {
                      setExitGuardOpen(false);
                      order.mutate({
                        thesisAccepted: true,
                        userOverride: equityPlacement.overrideRequired,
                        protectExits,
                      });
                    }}
                  >
                    Place trade
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {overrideOpen ? (
        <div
          className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="trade-override-title"
          data-testid="trade-override"
        >
          <div className="order-cert-card w-full max-w-lg">
            <div className="order-cert-frame">
              <div className="order-cert-inner order-cert-stack">
                <h2 id="trade-override-title" className="order-cert-title">
                  Proceed at my own risk
                </h2>
                <p className="order-cert-copy" data-testid="trade-override-body">
                  Not recommended. {overrideReasons}. This does not send the order until you confirm.
                </p>
                <div className="order-cert-actions">
                  <button
                    type="button"
                    className="order-cert-dismiss order-cert-dismiss-secondary"
                    data-testid="trade-override-cancel"
                    onClick={() => setOverrideOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="order-cert-dismiss disabled:opacity-40"
                    data-testid="trade-override-proceed"
                    disabled={order.isPending}
                    onClick={() => {
                      setOverrideOpen(false);
                      order.mutate({ thesisAccepted: true, userOverride: true });
                    }}
                  >
                    Proceed at my own risk
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {order.isPending || progressComplete ? (
        <OrderSubmitProgress
          phase={order.isPending ? "submitting" : submitPhase}
          facts={submitFacts}
          onSettled={order.isPending ? undefined : finishOrderProgress}
        />
      ) : null}

      {orderRefusal !== null && !order.isPending && !progressComplete ? (
        <OrderRefusalDialog
          reason={orderRefusal}
          onViewPortfolio={() => nav("/portfolio")}
          onClose={() => setOrderRefusal(null)}
        />
      ) : null}

      {orderConfirmation && !order.isPending && !progressComplete ? (
        <OrderConfirmationCertificate
          details={orderConfirmation}
          onDismiss={() => {
            setOrderConfirmation(null);
            refreshDeskQueries(qc);
            nav("/app");
          }}
        />
      ) : null}
      </div>
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
