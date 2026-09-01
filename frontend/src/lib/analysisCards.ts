import { detectCatalysts, type Catalyst } from "./patterns";
import { computeSeries, sliceSeries, type PlotSeries } from "./plotChart";
import { supportResistance, type OhlcBar } from "./ta";

export type AnalysisCard = {
  id: string;
  name: string;
  kind: "study" | "catalyst";
  bias: "bullish" | "bearish" | "neutral";
  body: string;
  markId?: string;
};

export type AnalysisContext = {
  /** Full loaded series; trailing studies warm up on it, truncated at the window end. */
  contextBars?: OhlcBar[];
  /** Daily series for daily-based pivot values. */
  dailyBars?: OhlcBar[];
};

function fmt(n: number | null | undefined, d = 2) {
  if (n == null || !Number.isFinite(n)) return "n/a";
  return n.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
}

/**
 * Bars used to evaluate the studies: the captured window plus whatever history
 * preceded it, cut off at the last visible bar so nothing after the capture can
 * leak into a value. This is how TradingView evaluates a study at a given bar.
 */
export function analysisSeriesBars(window: OhlcBar[], contextBars?: OhlcBar[]): OhlcBar[] {
  if (!window.length) return window;
  if (!contextBars?.length) return window;
  const endT = window[window.length - 1].t;
  const endIdx = contextBars.findIndex((b) => b.t === endT);
  if (endIdx < 0) return window;
  const startT = window[0].t;
  const startIdx = contextBars.findIndex((b) => b.t === startT);
  if (startIdx < 0) return window;
  return contextBars.slice(0, endIdx + 1);
}

export function buildAnalysisCards(
  symbol: string,
  timeframe: string,
  bars: OhlcBar[],
  ctx: AnalysisContext = {},
): { cards: AnalysisCard[]; catalysts: Catalyst[]; series: PlotSeries } {
  const evalBars = analysisSeriesBars(bars, ctx.contextBars);
  const fullSeries = computeSeries(evalBars, { dailyBars: ctx.dailyBars, timeframe });
  const warmup = Math.max(0, evalBars.length - bars.length);
  const series = warmup > 0 ? sliceSeries(fullSeries, warmup) : fullSeries;
  if (bars.length < 5) {
    const names: [string, string][] = [
      ["study-ema", "EMA stack 9 / 21 / 50 / 100 / 200"],
      ["study-macd", "MACD 12 / 26 / 9"],
      ["study-rsi", "RSI 14"],
      ["study-bb", "Bollinger Bands 20/2"],
      ["study-pivots", "Pivot points P / R1–R5 / S1–S5"],
      ["study-sr", "Support & resistance"],
      ["study-supertrend", "SuperTrend ATR 10 / 3"],
      ["study-volume", "Volume"],
      ["study-forecast", "Captured-window trend forecast"],
    ];
    return {
      cards: names.map(([id, name]) => ({
        id,
        name,
        kind: "study" as const,
        bias: "neutral" as const,
        body: `Waiting on OHLC for ${symbol} ${timeframe} via /market/bars so this ${name} write-up can be driven by live values rather than a generic template. No pattern or signal is claimed until bars exist.`,
      })),
      catalysts: [],
      series,
    };
  }
  const catalysts = detectCatalysts(bars, series);
  const i = bars.length - 1;
  const b = bars[i];
  const px = b.c;
  const ema = {
    9: series.ema9[i],
    21: series.ema21[i],
    50: series.ema50[i],
    100: series.ema100[i],
    200: series.ema200[i],
  };
  const sma50 = series.sma50[i];
  const sma200 = series.sma200[i];
  const bb = { mid: series.bb.mid[i], upper: series.bb.upper[i], lower: series.bb.lower[i], width: series.bb.width[i] };
  const st = series.st[i];
  const m = { line: series.macd.line[i], signal: series.macd.signal[i], hist: series.macd.histogram[i] };
  const r = series.rsi[i];
  const piv = series.pivots;
  const volAvg = bars.slice(-20).reduce((a, x) => a + x.v, 0) / Math.min(20, bars.length);
  const volRatio = volAvg ? b.v / volAvg : 1;
  const stackedBull = ema[9] > ema[21] && ema[21] > ema[50] && ema[50] > ema[100] && ema[100] > ema[200];
  const stackedBear = ema[9] < ema[21] && ema[21] < ema[50] && ema[50] < ema[100] && ema[100] < ema[200];
  const zones = supportResistance(bars);
  const rsiPrev = series.rsi.slice(-6, -1);
  const rsiTrend = rsiPrev.length ? (r > rsiPrev[0] ? "rising" : "falling") : "flat";
  const histPrev = series.macd.histogram[Math.max(0, i - 3)];
  const histExpanding = Math.abs(m.hist) > Math.abs(histPrev);
  const dualGate =
    px > st.value && px > ema[200] ? "confirmed-bullish dual-gate (price above SuperTrend and above EMA200)" : px < st.value && px < ema[200] ? "confirmed-bearish dual-gate (price below SuperTrend and below EMA200)" : "mixed gates (price disagrees between SuperTrend and EMA200 — reduce directional size)";
  const macdState = m.line >= m.signal ? "bullish MACD cross state" : "bearish MACD cross state";
  const rsiZone = r > 70 ? "overbought (>70)" : r < 30 ? "oversold (<30)" : r >= 40 && r <= 60 ? "neutral 40–60" : r > 60 ? "bullish momentum 60–70" : "bearish momentum 30–40";
  const confluence =
    `Confluence on this ${symbol} ${timeframe} capture: last close ${fmt(px)} vs EMA9 ${fmt(ema[9])} / EMA21 ${fmt(ema[21])} / EMA200 ${fmt(ema[200])}; SuperTrend ${fmt(st.value)} (${st.direction === 1 ? "bullish" : "bearish"}); MACD line ${fmt(m.line, 4)} vs signal ${fmt(m.signal, 4)} (${macdState}); RSI14 ${fmt(r, 2)} (${rsiZone}); Bollinger mid ${fmt(bb.mid)} with width ${fmt(bb.width * 100, 2)}%. ` +
    `The dual-gate read is ${dualGate}. ` +
    (stackedBull ? "EMA stack 9>21>50>100>200 agrees with a long-side overlay." : stackedBear ? "Inverted EMA stack 9<21<50<100<200 agrees with a short-side overlay." : "Mixed EMA stack so oscillator signals need a gate confirmation before they are treated as a breakout.");

  const windowFrom = bars[0].t;
  const windowTo = b.t;
  const studies: AnalysisCard[] = [
    {
      id: "study-window",
      name: "Captured chart window",
      kind: "study",
      bias: "neutral",
      body:
        `What it is: the exact chart state frozen when Scan was pressed — every number in the following cards is computed from these bars and nothing else. ` +
        `Captured window: ${symbol} on ${timeframe}, ${bars.length} visible bars from ${windowFrom} to ${windowTo}. ` +
        `Warm-up history used ahead of the window so trailing studies are defined: ${warmup} bars (nothing after ${windowTo} is used, so no value can look ahead of the capture). ` +
        `Window range: low ${fmt(Math.min(...bars.map((x) => x.l)))}, high ${fmt(Math.max(...bars.map((x) => x.h)))}, first close ${fmt(bars[0].c)}, last close ${fmt(px)}. ` +
        `Total captured volume ${fmt(bars.reduce((a, x) => a + (x.v ?? 0), 0), 0)}. ` +
        `To reproduce any figure below, take those ${bars.length} bars (plus the ${warmup} warm-up bars) and run the documented parameters — EMA 9/21/50/100/200, SMA 50/200, Bollinger 20/2, MACD 12/26/9, RSI 14, SuperTrend ATR 10 factor 3, Pivot Points Standard Traditional. ` +
        `Studies that cannot be defined on this much history are reported as "n/a" instead of being extrapolated from the first close.`,
    },
    {
      id: "study-ema",
      name: "EMA stack 9 / 21 / 50 / 100 / 200",
      kind: "study",
      bias: stackedBull ? "bullish" : stackedBear ? "bearish" : "neutral",
      body:
        `What it is: the exponential moving-average stack is a five-period trend map. EMA 9 (blue) and EMA 21 (cyan) occupy two of the five native Advanced Chart study slots on the price pane; EMA 50 (green), EMA 100 (purple), and EMA 200 (red) are aligned overlays on the same candles with last-value tags on the scale. Each EMA is a recency-weighted mean of closes on this exact ${symbol} ${timeframe} series; shorter lengths (9, 21) describe impulse, 50 is the swing filter, 100 is the institutional S/R mean, and 200 is the structural regime gate used with SuperTrend. ` +
        `Current reading: last close ${fmt(px)} (O ${fmt(b.o)} / H ${fmt(b.h)} / L ${fmt(b.l)}). Live values are EMA9 ${fmt(ema[9])}, EMA21 ${fmt(ema[21])}, EMA50 ${fmt(ema[50])}, EMA100 ${fmt(ema[100])}, EMA200 ${fmt(ema[200])}. Distances from spot: 9 ${fmt(px - ema[9])}, 21 ${fmt(px - ema[21])}, 50 ${fmt(px - ema[50])}, 100 ${fmt(px - ema[100])}, 200 ${fmt(px - ema[200])}. Price is ${px >= ema[9] ? "above" : "below"} the 9, ${px >= ema[21] ? "above" : "below"} the 21, and ${px >= ema[200] ? "above" : "below"} the 200-period gate. ` +
        `What it depicts: ${
          stackedBull
            ? "a fully aligned bullish ribbon (9>21>50>100>200) — the documented highest-conviction directional long. The 9–21 pair is the impulse; the 200 is the floor."
            : stackedBear
              ? "a fully inverted bearish ribbon (9<21<50<100<200). Pullbacks that tag the ribbon and fail are the documented short entries, with the 200 acting as a ceiling."
              : "a mixed ribbon, so conviction is reduced. Treat 9/21 as impulse only and 50/200 as a regime filter rather than a green-light trend."
        } Golden-cross state (EMA50 vs EMA200) is ${ema[50] > ema[200] ? `constructive — 50 (${fmt(ema[50])}) is above 200 (${fmt(ema[200])})` : `impaired — 50 (${fmt(ema[50])}) is below 200 (${fmt(ema[200])}), a death-cross condition`}. ` +
        `What it predicts: ${
          stackedBull
            ? `continuation while price holds the 9–21 ribbon and EMA200 (${fmt(ema[200])}) remains the structural floor. A close back through EMA21 ${fmt(ema[21])} is the first warning; a close through EMA200 would flip the gate.`
            : stackedBear
              ? `continuation lower while rejected rallies fail at the ribbon. Reclaiming EMA21 ${fmt(ema[21])} then EMA200 ${fmt(ema[200])} would be the first structural repair.`
              : `chop until the 9/21 pair re-aligns with the 50/200 regime. Do not size a breakout until the stack stops disagreeing.`
        } ` +
        confluence,
    },
    {
      id: "study-sma50",
      name: "SMA 50",
      kind: "study",
      bias: px >= sma50 ? "bullish" : "bearish",
      body:
        `What it is: the 50-period simple moving average is the equally weighted mean of the last 50 closes on this captured window. Unlike EMA50 (${fmt(ema[50])}), it does not overweight the most recent bars, so it lags the exponential ribbon and is the slower confirmation of the same swing. ` +
        `Current reading: SMA50 ${fmt(sma50)}. Last close ${fmt(px)} is ${px >= sma50 ? "holding above" : "trading below"} it by ${fmt(Math.abs(px - sma50))} (${fmt((Math.abs(px - sma50) / px) * 100, 2)}% of spot). EMA50 on the same bars is ${fmt(ema[50])}; the two 50-period means ${ (px >= sma50) === (px >= ema[50]) ? "agree" : "disagree" } on which side of the swing filter price sits. ` +
        `What it depicts: a mid-horizon mean-reversion magnet and dynamic S/R. APEX uses SMA50 as a companion to EMA50 so a signal is not an exponential-smoothing artifact. ` +
        `What it predicts: a close back through ${fmt(sma50)} would flip this mean from ${px >= sma50 ? "dynamic support to resistance" : "resistance to support"}. If SMA50 and EMA50 both sit ${px >= sma50 ? "beneath" : "above"} price while MACD is ${macdState} and RSI is ${rsiZone}, the swing filter is confirming that oscillator. If they disagree, wait for the slower SMA50 to catch up before treating a 9/21 cross as a regime change. ` +
        confluence,
    },
    {
      id: "study-sma200",
      name: "SMA 200",
      kind: "study",
      bias: px >= sma200 ? "bullish" : "bearish",
      body:
        `What it is: the 200-period simple moving average is the long-horizon equally weighted mean — the slow twin of EMA200. Docs specify golden/death-cross language on the 50/200 EMA pair; SMA200 is the confirmation that the 200-gate is not just exponential smoothing. ` +
        `Current reading: SMA200 ${fmt(sma200)}, EMA200 ${fmt(ema[200])}, last price ${fmt(px)}. Spot is ${px >= sma200 ? `${fmt(px - sma200)} above` : `${fmt(sma200 - px)} below`} the 200 SMA (${fmt(((px - sma200) / px) * 100, 2)}% of spot). ` +
        `What it depicts: ${px >= sma200 ? "classic bull-market posture (price above the long mean)" : "classic bear-market posture (price below the long mean)"}. Distance stretched far from SMA200 often precedes mean-reversion toward ${fmt(sma200)}; compressed distance often precedes a trend leg once the 50-period means re-align. ` +
        `What it predicts: ${
          px >= sma200 && px >= ema[200]
            ? `as long as SuperTrend (${fmt(st.value)}) stays bullish and RSI holds above 40, dips toward SMA200 ${fmt(sma200)} are buy-the-gate tests rather than regime breaks.`
            : px < sma200 && px < ema[200]
              ? `rallies into SMA200 ${fmt(sma200)} are sell-the-gate tests while SuperTrend is ${st.direction === 1 ? "still bullish — mixed, so stand down" : "bearish and agreeing with the 200s"}.`
              : `the two 200-period means disagree with spot; do not treat this as a clean regime until close, SMA200, and EMA200 stack on one side.`
        } ` +
        confluence,
    },
    {
      id: "study-bb",
      name: "Bollinger Bands 20/2",
      kind: "study",
      bias: px > bb.mid ? "bullish" : "bearish",
      body:
        `What it is: Bollinger Bands on this window are the documented 20-period SMA ± 2 standard deviations. The midline is a 20-bar mean; the envelope width is realized volatility. They live on the same price pane as the EMA 9/21 ribbon on the TradingView chart. ` +
        `Current reading: midline ${fmt(bb.mid)}, upper ${fmt(bb.upper)}, lower ${fmt(bb.lower)}. Band width ${fmt(bb.width, 4)} (${fmt(bb.width * 100, 2)}% of the mid). Last close ${fmt(px)} is ${
          px > bb.upper ? `outside the upper band (over-extension of ${fmt(px - bb.upper)})` : px < bb.lower ? `outside the lower band (undershoot of ${fmt(bb.lower - px)})` : `inside the envelope, ${fmt(px - bb.mid)} from the midline`
        }. ` +
        `What it depicts: ${
          bb.width < 0.04
            ? `a squeeze (width compressed below 4%). Docs treat this as imminent expansion; the first accepted close outside ${fmt(bb.upper)} or ${fmt(bb.lower)} sets direction.`
            : `an already expanded regime rather than a coiled breakout. Direction is inferred from which side of ${fmt(bb.mid)} price holds, not from a squeeze release.`
        } RSI is ${fmt(r, 2)} (${rsiZone})${px > bb.upper && r > 70 ? " — the documented overbought warning: upper-band tag plus RSI>70" : px < bb.lower && r < 30 ? " — the documented oversold bounce candidate: lower-band tag plus RSI<30" : ""}. ` +
        `What it predicts: bullish playbook is close through the midline, hold, then tag/hold the upper band as support. Bearish playbook is lose the midline, hold, then break the lower band which then acts as resistance. W-pattern (flush to lower, reclaim mid, retest, break out) and M-pattern (tag upper, back to mid, fail, break mid) are the documented shapes. ${macdState} ${histExpanding ? "with an expanding histogram" : "with a contracting histogram"} ${m.line >= m.signal && px > bb.mid ? "agrees with holding the upper half of the envelope" : m.line < m.signal && px < bb.mid ? "agrees with holding the lower half of the envelope" : "currently disagrees with the band half — wait for MACD to confirm a midline break"}. ` +
        confluence,
    },
    {
      id: "study-macd",
      name: "MACD 12 / 26 / 9",
      kind: "study",
      bias: m.line >= m.signal ? "bullish" : "bearish",
      body:
        `What it is: MACD is the 12-period EMA minus the 26-period EMA of closes, with a 9-period EMA signal. It is plotted as a full TradingView sub-pane (histogram + two lines), not a sparkline. It measures momentum of the same captured ${symbol} ${timeframe} closes sitting on the price pane. ` +
        `Current reading: line ${fmt(m.line, 4)}, signal ${fmt(m.signal, 4)}, histogram ${fmt(m.hist, 4)}. The line is ${m.line >= m.signal ? "above" : "below"} the signal and ${m.line >= 0 ? "north of the zero line" : "south of the zero line"} — ${macdState}. Histogram is ${m.hist >= 0 ? "positive" : "negative"} and ${histExpanding ? `expanding versus the print three bars ago (${fmt(histPrev, 4)}) — momentum still feeds the current side` : `contracting versus ${fmt(histPrev, 4)} — momentum is fading even if the cross has not flipped`}. ` +
        `What it depicts: zero-line side is trend; signal cross is the trigger; histogram slope is acceleration. Bullish divergence is price lower-low vs MACD higher-low (seller exhaustion). Bearish divergence is price higher-high vs MACD lower-high (buyer exhaustion). ` +
        `What it predicts: ${
          m.line >= m.signal && m.hist >= 0
            ? `as long as histogram stays positive, pullbacks toward EMA21 ${fmt(ema[21])} that hold SuperTrend ${fmt(st.value)} are continuation longs. A histogram flip below zero while RSI is ${fmt(r, 2)} would be the first momentum failure.`
            : m.line < m.signal && m.hist < 0
              ? `as long as histogram stays negative, rallies into EMA21 ${fmt(ema[21])} that fail SuperTrend ${fmt(st.value)} are continuation shorts. A histogram reclaim of zero while RSI is ${fmt(r, 2)} would be the first repair.`
              : `cross and histogram disagree (line vs zero). Treat this as a pause, not a fresh trigger, until they realign.`
        } ${
          catalysts.some((c) => c.name.includes("MACD"))
            ? "This window currently carries a high-confidence MACD catalyst on the captured OHLC; the matching carousel card is linked to that print."
            : "No high-confidence MACD cross or divergence printed on the last few bars; the live values above are state, not a fresh trigger."
        } ` +
        confluence,
    },
    {
      id: "study-rsi",
      name: "RSI 14",
      kind: "study",
      bias: r >= 60 ? "bullish" : r <= 40 ? "bearish" : "neutral",
      body:
        `What it is: the 14-period Relative Strength Index is a bounded 0–100 momentum oscillator on this captured close series. It occupies a full TradingView sub-pane beneath MACD, with the conventional 70/30 rails. It does not measure price level; it measures the velocity of up-closes versus down-closes. ` +
        `Current reading: RSI14 ${fmt(r, 2)}, ${rsiTrend} versus the prior five prints (${rsiPrev.map((v) => fmt(v, 1)).join(" → ") || "n/a"}). Zone: ${rsiZone}. ${
          r > 70 ? "Docs favor puts / bearish spreads while >70, unless a strong uptrend is holding above 70 as a momentum ceiling." : r < 30 ? "Docs favor calls / bullish spreads while <30, provided the SuperTrend/EMA200 gates are not still fully bearish." : r >= 40 && r <= 60 ? "Neutral 40–60 is range-bound, premium-selling / iron-condor territory rather than a directional breakout." : r > 60 ? "Sustaining 60–70 marks a strong uptrend that can stay elevated; a cross through 70 is late-trend, not an automatic short." : "Sustaining 40–30 marks a strong downtrend; a cross through 30 is late-trend, not an automatic long."
        } ` +
        `What it depicts: Project APEX long is RSI dipping below 30 and immediately reclaiming 30 while SuperTrend holds. Classic short is RSI crossing 70 then failing back below 70 and staying there. In a documented bull run, 40–50 is support; in a bear trend, 50–60 is resistance. Divergence: price lower-low vs RSI higher-low is bullish exhaustion; price higher-high vs RSI lower-high is bearish exhaustion. ` +
        `What it predicts: ${
          r > 70 && px > bb.upper
            ? `RSI overbought coinciding with a close outside the upper Bollinger (${fmt(bb.upper)}) is the documented over-extension. Mean-reversion toward midline ${fmt(bb.mid)} is the base case unless MACD histogram is still expanding (${histExpanding ? "it is" : "it is not"}).`
            : r < 30 && px < bb.lower
              ? `RSI oversold coinciding with a close outside the lower Bollinger (${fmt(bb.lower)}) is the documented bounce candidate, only if SuperTrend (${fmt(st.value)}) is not still a rigid ceiling.`
              : `with RSI at ${fmt(r, 2)} and MACD ${macdState}, the oscillator pair ${ (r >= 50) === (m.line >= m.signal) ? "agrees" : "disagrees" } — ${ (r >= 50) === (m.line >= m.signal) ? "momentum is internally consistent on this chart" : "wait for RSI and MACD to stop arguing before treating a 9/21 EMA tap as a breakout" }.`
        } ` +
        confluence,
    },
    {
      id: "study-volume",
      name: "Volume",
      kind: "study",
      bias: px >= bars[Math.max(0, i - 20)].c && volRatio > 1 ? "bullish" : px < bars[Math.max(0, i - 20)].c && volRatio > 1 ? "bearish" : "neutral",
      body:
        `What it is: volume is native on the TradingView price pane (not one of the five study slots). It is the participation count behind each captured bar and the confirmation layer for every EMA, MACD, and RSI signal on this chart. ` +
        `Current reading: last bar volume ${fmt(b.v, 0)} versus the 20-bar average ${fmt(volAvg, 0)} — a ${fmt((volRatio - 1) * 100, 1)}% ${volRatio >= 1 ? "premium" : "discount"} to typical participation. This bar is ${volRatio >= 3 ? "an unusual-activity print (≥3× average)" : volRatio >= 1.4 ? "elevated but not a 3× spike" : "in line with or quieter than the local average"}. Price over the last 20 captured bars is ${px >= bars[Math.max(0, i - 20)].c ? "higher" : "lower"} (${fmt(bars[Math.max(0, i - 20)].c)} → ${fmt(px)}). ` +
        `What it depicts: Project APEX — higher highs with expanding volume = buyer demand; lower lows with following volume = seller environment. Bullish volume divergence is price lower-lows with volume higher-lows (demand at the lows). Bearish is price higher-highs on shrinking volume highs (distribution). ` +
        `What it predicts: volume is ${volRatio > 1 ? "confirming" : "not confirming"} the 20-bar directional drift. ${
          volRatio > 1 && m.line >= m.signal && r >= 50
            ? "Participation agrees with the bullish MACD/RSI pair — a break of nearby resistance is more trustworthy."
            : volRatio > 1 && m.line < m.signal && r <= 50
              ? "Participation agrees with the bearish MACD/RSI pair — a break of nearby support is more trustworthy."
              : "Quiet or conflicting volume means treat oscillator crosses as provisional until a 1.4×+ bar prints in the breakout direction."
        } ` +
        confluence,
    },
    {
      id: "study-pivots",
      name: "Pivot points P / R1–R5 / S1–S5",
      kind: "study",
      bias: piv ? (px >= piv.pp ? "bullish" : "bearish") : "neutral",
      body: (() => {
        // Evidence: daily prior H/L/C when dailyBars warmed the ladder; else prior bar on the capture.
        const daily = ctx.dailyBars ?? [];
        const pivotSrc =
          daily.length >= 2 ? daily[daily.length - 2] : bars.length >= 2 ? bars[i - 1] : null;
        const srcLabel =
          daily.length >= 2
            ? `prior completed daily bar (${pivotSrc?.t ?? "n/a"})`
            : `prior bar on this ${timeframe} capture (${pivotSrc?.t ?? "n/a"})`;
        if (!piv || !pivotSrc) {
          return `Insufficient prior bar to project a pivot ladder on this ${symbol} ${timeframe} capture. ${confluence}`;
        }
        return (
          `What it is: standard floor-trader pivots projected from the prior session high/low/close. P = (H+L+C)/3 with R1–R5 / S1–S5 as the classic ladder (Rn = High + n·(P−Low), Sn = Low − n·(High−P)). SuperTrend/Traditional pivots are analysis-only here — they are not drawn on the desk TradingView chart. ` +
          `Current reading: ${srcLabel} H/L/C ${fmt(pivotSrc.h)} / ${fmt(pivotSrc.l)} / ${fmt(pivotSrc.c)}. Ladder: P ${fmt(piv.pp)}, R1 ${fmt(piv.r1)}, R2 ${fmt(piv.r2)}, R3 ${fmt(piv.r3)}, R4 ${fmt(piv.r4)}, R5 ${fmt(piv.r5)}, S1 ${fmt(piv.s1)}, S2 ${fmt(piv.s2)}, S3 ${fmt(piv.s3)}, S4 ${fmt(piv.s4)}, S5 ${fmt(piv.s5)}. Last close ${fmt(px)} is ${px >= piv.pp ? `above the central pivot — documented upside continuation with P as support` : `below the central pivot — documented downside continuation with P as resistance`}. Nearest magnet is ${
            [
              ["P", piv.pp],
              ["R1", piv.r1],
              ["R2", piv.r2],
              ["R3", piv.r3],
              ["R4", piv.r4],
              ["R5", piv.r5],
              ["S1", piv.s1],
              ["S2", piv.s2],
              ["S3", piv.s3],
              ["S4", piv.s4],
              ["S5", piv.s5],
            ].sort((a, b) => Math.abs(px - (a[1] as number)) - Math.abs(px - (b[1] as number)))[0][0]
          }. ` +
          `What it depicts: a session geometry for stops and option strikes. R-levels are successive upside magnets; S-levels are successive downside magnets. ` +
          `What it predicts: ${
            px >= piv.pp
              ? `held P ${fmt(piv.pp)} projects R1 ${fmt(piv.r1)} then R2 ${fmt(piv.r2)} (and R3–R5 if momentum expands). That path is only high-confidence if SuperTrend (${fmt(st.value)}) is bullish and MACD remains ${macdState}.`
              : `lost P ${fmt(piv.pp)} projects S1 ${fmt(piv.s1)} then S2 ${fmt(piv.s2)} (and S3–S5 if selling expands). That path is only high-confidence if SuperTrend is bearish and RSI stays ${rsiZone}.`
          } Strikes clustered on these prints are the documented natural anchors. ` +
          confluence
        );
      })(),
    },
    {
      id: "study-supertrend",
      name: "SuperTrend ATR 10 / 3",
      kind: "study",
      bias: st.direction === 1 ? "bullish" : "bearish",
      body:
        `What it is: SuperTrend is an ATR trailing stop computed on the same captured OHLC (ATR length 10, multiplier 3). It is analysis-only on the scan carousel — SuperTrend is not drawn on the desk TradingView chart (which keeps EMA 9/21, Bollinger, MACD, RSI, and volume). ` +
        `Current reading: SuperTrend ${fmt(st.value)}, ATR ${fmt(st.atr, 4)}, direction ${st.direction === 1 ? "bullish (line beneath price)" : "bearish (line above price)"}. Close ${fmt(px)} is ${px >= st.value ? "above" : "below"} the line by ${fmt(Math.abs(px - st.value))} (${fmt((Math.abs(px - st.value) / px) * 100, 2)}% of spot). EMA200 is ${fmt(ema[200])}. Dual-gate: ${dualGate}. ` +
        `What it depicts: a close through the red line starts the uptrend and that print becomes support/stop; a close through the green line starts the downtrend and that print becomes resistance. Combined with the 200 EMA gate: price above SuperTrend AND above 200 EMA = only long signals; below both = only short signals. ` +
        `What it predicts: ${
          px > st.value && px > ema[200]
            ? `only longs while this dual-gate holds. A close through ${fmt(st.value)} would flip the stop; a close through EMA200 ${fmt(ema[200])} would break the regime filter. MACD ${macdState} and RSI ${fmt(r, 2)} ${r >= 50 ? "currently support holding the long gate" : "are lagging the long gate — size down until RSI reclaims 50"}.`
            : px < st.value && px < ema[200]
              ? `only shorts while this dual-gate holds. Reclaiming ${fmt(st.value)} then EMA200 ${fmt(ema[200])} is the repair sequence. MACD ${macdState} and RSI ${fmt(r, 2)} ${r <= 50 ? "currently support holding the short gate" : "are lagging the short gate — size down until RSI loses 50"}.`
              : `gates are mixed. Do not treat a 9/21 EMA cross or a MACD signal cross as a breakout until SuperTrend and EMA200 stack on the same side of ${fmt(px)}.`
        } ` +
        confluence,
    },
    {
      id: "study-sr",
      name: "Support & resistance",
      kind: "study",
      bias: "neutral",
      body:
        `What it is: support and resistance levels derived from swing-touch clusters (and volume-profile nodes when swings are thin). They are analysis-only on this carousel — S/R trendlines are not drawn on the desk TradingView chart or the frozen snapshot, so they never glow or highlight on the graph. ` +
        `Current reading: ${
          zones.length
            ? `ranked nodes ${zones
                .slice(0, 6)
                .map((z) => `${z.kind === "support" ? "S" : "R"} ${fmt(z.price)}`)
                .join(", ")}. Nearest to last close ${fmt(px)} is ${fmt(zones.slice().sort((a, b) => Math.abs(a.price - px) - Math.abs(b.price - px))[0].price)}.`
            : "not enough distribution to rank nodes on this window."
        } Session range ${fmt(Math.min(...bars.map((x) => x.l)))}–${fmt(Math.max(...bars.map((x) => x.h)))}. ` +
        `What it depicts: a close through resistance is an upside escalation; a close through support is a downside escalation. A break that retreats through the same level in a short span is a false breakout and implies the opposite pressure. ` +
        `What it predicts: strikes parked on these nodes are the natural spread anchors. A break is high-confidence only when volume is ${volRatio >= 1.4 ? "elevated (this bar qualifies)" : "quiet on this bar — wait for expansion"} and the dual-gate is not mixed (${dualGate}). MACD ${macdState} and RSI ${fmt(r, 2)} ${ (r >= 50) === (m.line >= m.signal) ? "agree on the directional side of a break" : "still disagree, so fade weak breaks back into the node" }. ` +
        confluence,
    },
  ];

  const catalystCards: AnalysisCard[] = catalysts.map((c) => ({
    id: `cat-${c.id}`,
    name: c.name,
    kind: "catalyst",
    bias: c.bias,
    markId: c.id,
    body:
      `${c.explain} ` +
      `This mark is computed on the same captured ${symbol} ${timeframe} OHLC used to freeze the snapshot (bar ${c.barIndex + 1} of ${bars.length}, session ${bars[c.barIndex]?.t ?? "n/a"}, price reference ${fmt(c.price)}${c.price2 != null ? `–${fmt(c.price2)}` : ""}). APEX only discusses high-confidence textbook prints and structural breaks that actually appear in this viewport — not every wick. The frozen snapshot extra-draws S/R as trendlines/horizontals only; this print is explained here rather than boxed over the candles. ` +
      `Bias is ${c.bias}. ${
        c.bias === "bullish"
          ? `It confirms long-side price action and still requires the EMA/SuperTrend dual-gate (${dualGate}) before it is treated as a breakout rather than a noise print. Forward path: continuation while that gate holds.`
          : `It confirms short-side price action and still requires the EMA/SuperTrend dual-gate (${dualGate}) before it is treated as a breakdown rather than a noise print. Forward path: continuation lower while that gate holds.`
      } ` +
      `At the same moment MACD is ${macdState} (line ${fmt(m.line, 4)} / signal ${fmt(m.signal, 4)} / hist ${fmt(m.hist, 4)}), RSI14 is ${fmt(r, 2)} (${rsiZone}), last close is ${fmt(px)} versus EMA9 ${fmt(ema[9])} and EMA200 ${fmt(ema[200])}, and SuperTrend is ${fmt(st.value)} ${st.direction === 1 ? "bullish" : "bearish"}. ` +
      `${ (c.bias === "bullish") === (m.line >= m.signal) && (c.bias === "bullish") === (r >= 50) ? "Oscillators agree with this mark — it is a confluence catalyst, not a lone candle." : "Oscillators do not fully agree with this mark; treat it as a location of interest, not an automatic entry, until MACD and RSI stop disagreeing." } ` +
      confluence,
  }));

  return { cards: [...studies, ...catalystCards], catalysts, series };
}
