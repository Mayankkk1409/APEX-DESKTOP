"""Deep Scan sentiment layer — Full Document §7.1.

Weights (docs):
  Financial News NLP 40% · Options flow 35% · Social 15% · Put/Call 10%

Rules:
  - Real Alpaca news only — never invent headlines.
  - Options flow / P/C derived from the selected-expiry chain when present.
  - Social is labeled unavailable until a live feed is wired (weight dropped).
  - Composite gauge is signed ``[-100, +100]``; ``score_0_100`` feeds the §8 composite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.analysis.news_nlp import score_articles
from app.analysis.score_bounds import assert_score_in_bounds
from app.config import Settings
from app.schemas.market import OptionChain
from app.services.news_authenticity import no_recent_news_message

WEIGHTS = {"news": 0.40, "options_flow": 0.35, "social": 0.15, "put_call": 0.10}


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _sentiment_band(score: float | None) -> str:
    """Map internal signed score to a five-band headline label."""
    if score is None:
        return "Neutral"
    if score <= -60:
        return "Very Bearish"
    if score <= -20:
        return "Bearish"
    if score >= 60:
        return "Very Bullish"
    if score >= 20:
        return "Bullish"
    return "Neutral"


def _volume_context(call_vol: int, put_vol: int, avg_equity_vol: float | int | None) -> str | None:
    total = call_vol + put_vol
    if total <= 0:
        return None
    if avg_equity_vol and float(avg_equity_vol) > 0:
        ratio = total / float(avg_equity_vol)
        if ratio > 0.5:
            tone = "elevated"
        elif ratio < 0.05:
            tone = "light"
        else:
            tone = "typical"
        return (
            f"Combined {total:,} contracts on the selected expiry — {tone} vs "
            f"equity average daily volume ({int(float(avg_equity_vol)):,} shares/day)."
        )
    return f"Combined {total:,} contracts on the selected expiry."


def _notional_skew(call_notional: float | None, put_notional: float | None) -> str | None:
    if call_notional is None or put_notional is None:
        return None
    total = call_notional + put_notional
    if total <= 0:
        return None
    tilt = (call_notional - put_notional) / total
    if tilt > 0.15:
        return "call-heavy notional skew"
    if tilt < -0.15:
        return "put-heavy notional skew"
    return "balanced notional skew"


def _article_tone_counts(articles: list[dict]) -> tuple[int, int, int]:
    constructive = negative = 0
    for art in articles:
        score = art.get("nlp_score")
        if score is None:
            continue
        if score > 10:
            constructive += 1
        elif score < -10:
            negative += 1
    neutral = max(0, len(articles) - constructive - negative)
    return constructive, negative, neutral


def _news_tone_sentence(
    *,
    sym: str,
    news_count: int,
    news_score: float | None,
    sample_headlines: list[str],
    news_error: str | None = None,
) -> str:
    if not news_count or news_score is None:
        reason = (news_error or "").strip()
        # A rate limit is retried quietly. The desk must not print HTTP 429.
        if reason and "429" not in reason:
            return f"News for {sym} is unavailable: {reason}."
        return no_recent_news_message(sym)

    tone = "constructive"
    if news_score < -15:
        tone = "cautious"
    elif -15 <= news_score <= 15:
        tone = "mixed"

    if sample_headlines:
        if len(sample_headlines) == 1:
            h = sample_headlines[0]
            cited = f'"{h[:100]}{"…" if len(h) > 100 else ""}"'
            return (
                f"Headline flow on {sym} reads {tone} — the lead story, {cited}, "
                f"anchors today's {news_count}-article news tape."
            )
        cited = " and ".join(
            f'"{h[:80]}{"…" if len(h) > 80 else ""}"' for h in sample_headlines[:2]
        )
        return (
            f"Headline flow on {sym} reads {tone} across {news_count} recent stories, "
            f"including {cited}."
        )

    return f"Headline flow on {sym} reads {tone} across {news_count} recent articles."


def _flow_sentence(
    *,
    flow_label: str | None,
    call_vol: int | None,
    put_vol: int | None,
    avg_equity_vol: float | int | None,
    notional_skew: str | None,
    volume_context: str | None,
) -> str:
    total_opt = (call_vol or 0) + (put_vol or 0)
    if total_opt > 0:
        line = (
            f"On the selected expiry, options tape shows {call_vol or 0:,} call contracts "
            f"versus {put_vol or 0:,} puts"
        )
        if avg_equity_vol and float(avg_equity_vol) > 0:
            ratio = total_opt / float(avg_equity_vol)
            if ratio > 0.5:
                activity = "elevated"
            elif ratio < 0.05:
                activity = "light"
            else:
                activity = "typical"
            line += (
                f" — {activity} activity relative to average daily share volume "
                f"({int(float(avg_equity_vol)):,} shares/day)"
            )
        line += "."
        if flow_label and flow_label != "unavailable":
            lean = flow_label.replace("_", " ")
            line += f" Flow leans {lean}"
            if notional_skew:
                line += f" with {notional_skew}"
            line += "."
        return line
    if volume_context:
        return volume_context.rstrip(".") + "."
    return "Options flow on the selected expiry did not show a clear directional lean."


def _pc_sentence(pc_ratio: float | None, pc_label: str) -> str | None:
    if pc_ratio is None:
        return None
    pc_human = pc_label.replace("_", " ")
    if pc_ratio > 1.2:
        return (
            f"The put/call ratio at {pc_ratio:.2f} sits in a hedging-heavy zone, "
            f"suggesting {pc_human} positioning as puts outpace calls on volume."
        )
    if pc_ratio < 0.7:
        return (
            f"The put/call ratio at {pc_ratio:.2f} reflects aggressive call-side activity "
            f"({pc_human}), with calls dominating tape participation."
        )
    return (
        f"The put/call ratio at {pc_ratio:.2f} is neutral ({pc_human}), "
        "with neither calls nor puts clearly dominating volume."
    )


def _synthesis_paragraph(
    sym: str,
    *,
    band: str,
    score_0_100: float,
    composite: float | None,
    news_score: float | None,
    news_count: int,
    constructive: int,
    negative: int,
    neutral: int,
    sample_headlines: list[str],
    flow_score: float | None,
    flow_label: str | None,
    call_vol: int | None,
    put_vol: int | None,
    avg_equity_vol: float | int | None,
    pc_ratio: float | None,
    pc_label: str,
    pc_score: float | None,
    volume_context: str | None,
    notional_skew: str | None,
    renorm: dict[str, float],
    parts: dict[str, float | None],
    earnings_message: str | None,
    news_error: str | None = None,
) -> str:
    """Readable analyst brief — cites facts without exposing component math."""
    _ = (score_0_100, composite, flow_score, pc_score, renorm, parts, constructive, negative, neutral)
    sentences: list[str] = []

    sentences.append(
        _news_tone_sentence(
            sym=sym,
            news_count=news_count,
            news_score=news_score,
            sample_headlines=sample_headlines,
            news_error=news_error,
        )
    )
    sentences.append(
        _flow_sentence(
            flow_label=flow_label,
            call_vol=call_vol,
            put_vol=put_vol,
            avg_equity_vol=avg_equity_vol,
            notional_skew=notional_skew,
            volume_context=volume_context,
        )
    )

    pc_line = _pc_sentence(pc_ratio, pc_label)
    if pc_line:
        sentences.append(pc_line)

    # Closing synthesis ties the band to the evidence without formula dumps.
    if band in {"Very Bullish", "Bullish"}:
        close = f"Taken together, headline tone and options positioning support a {band.lower()} read on {sym}."
    elif band in {"Very Bearish", "Bearish"}:
        close = f"Taken together, headline tone and options positioning skew bearish on {sym}."
    elif composite is None:
        close = f"Live sentiment inputs for {sym} are unavailable, so no directional score is assigned."
    else:
        close = f"Overall, news and flow signals are balanced, leaving {sym} in a neutral posture."
    sentences.append(close)

    earn = (earnings_message or "").strip()
    if earn and earn not in (
        "Earnings calendar unavailable.",
        "Earnings calendar not loaded with this sentiment pass.",
    ):
        sentences.append(earn.rstrip(".") + ".")

    return " ".join(sentences[:5])


def _pc_signal(ratio: float | None) -> tuple[float | None, str]:
    """Map put/call volume ratio to signed score. Docs: >1.2 fear; <0.7 bullish."""
    if ratio is None:
        return None, "unavailable"
    if ratio > 1.2:
        # 1.2 → ~-35, 2.0+ → -100
        score = _clamp(-35.0 - (ratio - 1.2) * 80.0)
        return round(score, 1), "fear"
    if ratio < 0.7:
        score = _clamp(35.0 + (0.7 - ratio) * 90.0)
        return round(score, 1), "aggressive_bullish"
    # Linear through neutral band 0.7–1.2
    mid = 0.95
    score = _clamp((mid - ratio) / 0.25 * 25.0)
    return round(score, 1), "neutral"


def _flow_from_chain(chain: OptionChain | None, summary: dict[str, Any] | None) -> dict[str, Any]:
    """Chain-derived session flow. Not a true 48h dollar-premium tape — labeled honestly."""
    if chain is None or not chain.contracts:
        return {
            "status": "unavailable",
            "score": None,
            "label": "unavailable",
            "window": "selected_expiry_session",
            "call_volume": None,
            "put_volume": None,
            "call_notional_proxy": None,
            "put_notional_proxy": None,
            "net_notional_proxy": None,
            "delta_weighted_call_flow": None,
            "delta_weighted_put_flow": None,
            "unusual_activity_count": None,
            "source": None,
        }

    call_vol = put_vol = 0
    call_notional = put_notional = 0.0
    notional_obs = 0
    for c in chain.contracts:
        vol = c.volume or 0
        if c.side == "call":
            call_vol += vol
        else:
            put_vol += vol
        if vol > 0 and c.bid is not None and c.ask is not None and (c.bid > 0 or c.ask > 0):
            mid = (c.bid + c.ask) / 2.0
            notion = mid * vol * 100.0
            notional_obs += 1
            if c.side == "call":
                call_notional += notion
            else:
                put_notional += notion

    pc = None
    if call_vol > 0 and put_vol >= 0:
        pc = round(put_vol / call_vol, 3) if call_vol else None
    if summary and summary.get("put_call_volume_ratio") is not None:
        pc = summary["put_call_volume_ratio"]

    pc_score, pc_label = _pc_signal(pc)
    d_call = (summary or {}).get("delta_weighted_call_flow")
    d_put = (summary or {}).get("delta_weighted_put_flow")
    uoa = len((summary or {}).get("unusual_activity") or [])

    # Flow score leans on notional tilt when available, else P/C / delta-volume.
    flow_score: float | None = None
    if notional_obs >= 4 and (call_notional + put_notional) > 0:
        tilt = (call_notional - put_notional) / (call_notional + put_notional)
        flow_score = _clamp(tilt * 100.0)
    elif d_call is not None and d_put is not None and (d_call + d_put) > 0:
        tilt = (d_call - d_put) / (d_call + d_put)
        flow_score = _clamp(tilt * 100.0)
    elif pc_score is not None:
        flow_score = pc_score

    if flow_score is not None and uoa:
        # Unusual prints amplify the existing tilt slightly; never invent a direction.
        flow_score = _clamp(flow_score + (8.0 if flow_score >= 0 else -8.0) * min(uoa, 3))

    label = "bullish" if (flow_score or 0) > 20 else "bearish" if (flow_score or 0) < -20 else "mixed"
    return {
        "status": "live" if flow_score is not None else "partial",
        "score": round(flow_score, 1) if flow_score is not None else None,
        "label": label if flow_score is not None else "unavailable",
        "window": "selected_expiry_session",
        "call_volume": call_vol,
        "put_volume": put_vol,
        "put_call_volume_ratio": pc,
        "put_call_signal": pc_label,
        "call_notional_proxy": round(call_notional, 2) if notional_obs else None,
        "put_notional_proxy": round(put_notional, 2) if notional_obs else None,
        "net_notional_proxy": round(call_notional - put_notional, 2) if notional_obs else None,
        "delta_weighted_call_flow": d_call,
        "delta_weighted_put_flow": d_put,
        "unusual_activity_count": uoa,
        "contracts_with_notional": notional_obs,
        "source": chain.source,
        "expiry": chain.expiry,
    }


def _weighted_composite(parts: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    used: dict[str, float] = {}
    for key, weight in WEIGHTS.items():
        if parts.get(key) is None:
            continue
        used[key] = weight
    if not used:
        return None, {}
    total_w = sum(used.values())
    renorm = {k: w / total_w for k, w in used.items()}
    score = sum((parts[k] or 0.0) * renorm[k] for k in renorm)
    return round(_clamp(score), 1), renorm


_last_good_news: dict[str, list[dict]] = {}


def _news_cache_key(symbol: str | None) -> str:
    return (symbol or "").strip().upper()


async def fetch_alpaca_news(
    settings: Settings,
    *,
    symbol: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], str | None]:
    """Alpaca news rows, unchanged. Empty list plus a reason when the feed cannot be read."""
    if not settings.alpaca_keys_present:
        return [], "News feed unavailable — market data credentials not configured"
    import httpx

    url = f"{settings.resolved_data_base_url}/v1beta1/news"
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key_id,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
    }
    params: dict[str, Any] = {"limit": limit, "include_content": True}
    if symbol:
        params["symbols"] = symbol.upper()
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(url, headers=headers, params=params)
            if res.status_code >= 400:
                logger.warning("Alpaca news {} -> {}", res.status_code, res.text[:180])
                if res.status_code == 429:
                    cached = _last_good_news.get(_news_cache_key(symbol))
                    if cached:
                        return list(cached), None
                return [], f"News feed HTTP {res.status_code}"
            payload = res.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alpaca news failed for {}: {}", symbol or "market", exc)
        return [], f"News feed error: {exc}"
    news = payload.get("news") if isinstance(payload, dict) else None
    if not isinstance(news, list):
        return [], "News feed returned no articles"
    if news:
        _last_good_news[_news_cache_key(symbol)] = list(news)
    return news, None


async def _fetch_alpaca_news(symbol: str, settings: Settings, *, limit: int = 20) -> tuple[list[dict], str | None]:
    return await fetch_alpaca_news(settings, symbol=symbol, limit=limit)


def _earnings_alert(fundamentals: dict[str, Any] | None) -> dict[str, Any]:
    if not fundamentals:
        return {
            "active": False,
            "dte": None,
            "next_date": None,
            "message": "Earnings calendar not loaded with this sentiment pass.",
            "source": None,
        }
    cal = fundamentals.get("earnings_calendar") or {}
    dte = cal.get("dte")
    next_date = cal.get("next_date")
    last = cal.get("last_reported")
    if dte is not None and dte <= 7:
        return {
            "active": True,
            "dte": dte,
            "next_date": next_date,
            "message": f"Earnings in {dte} day(s) ({next_date}). Sentiment near events is noisy — size down.",
            "source": cal.get("source"),
        }
    if next_date:
        return {
            "active": False,
            "dte": dte,
            "next_date": next_date,
            "message": f"Next earnings {next_date}" + (f" ({dte} DTE)" if dte is not None else "") + ".",
            "source": cal.get("source"),
        }
    if last:
        return {
            "active": False,
            "dte": None,
            "next_date": None,
            "message": f"Last reported {last}. Next earnings date unavailable from the calendar feed.",
            "source": cal.get("source"),
        }
    return {
        "active": False,
        "dte": None,
        "next_date": None,
        "message": "Earnings calendar unavailable.",
        "source": None,
    }


async def build_sentiment_layer(
    symbol: str,
    settings: Settings,
    *,
    chain: OptionChain | None = None,
    chain_summary: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = symbol.upper()
    raw_news, news_err = await _fetch_alpaca_news(sym, settings)
    news_score, articles = score_articles(raw_news)
    fetched_at = datetime.now(timezone.utc).isoformat()
    if articles and news_score is not None:
        news_status = "live"
    elif news_err:
        news_status = "unavailable"
    else:
        news_status = "empty"
    news_block = {
        "status": news_status,
        "score": news_score,
        "count": len(articles),
        "method": "lexicon_v1",
        "source": "Alpaca News" if articles else None,
        "as_of": fetched_at if articles else None,
        "error": news_err,
        "articles": articles,
    }

    flow = _flow_from_chain(chain, chain_summary)
    pc_score, pc_label = _pc_signal(flow.get("put_call_volume_ratio"))
    put_call = {
        "status": "live" if pc_score is not None else "unavailable",
        "score": pc_score,
        "ratio": flow.get("put_call_volume_ratio"),
        "signal": pc_label,
        "rule": "P/C > 1.2 = fear; P/C < 0.7 = aggressive bullish",
        "source": flow.get("source"),
        "basis": "selected_expiry_volume",
    }

    social = {
        "status": "unavailable",
        "score": None,
        "label": "unavailable",
        "source": None,
    }

    composite, renorm = _weighted_composite(
        {
            "news": news_block["score"],
            "options_flow": flow.get("score"),
            "social": None,
            "put_call": put_call["score"],
        }
    )

    avg_equity_vol = None
    if fundamentals:
        health = fundamentals.get("company_health") or {}
        avg_equity_vol = health.get("avg_volume")
    volume_context = _volume_context(flow.get("call_volume") or 0, flow.get("put_volume") or 0, avg_equity_vol)
    notional_skew = _notional_skew(flow.get("call_notional_proxy"), flow.get("put_notional_proxy"))
    if volume_context:
        flow["volume_context"] = volume_context
    if notional_skew:
        flow["notional_skew"] = notional_skew

    score_0_100: float | None
    if composite is None:
        score_0_100 = None
        band = "Unavailable"
        bias = "unavailable"
    else:
        score_0_100 = assert_score_in_bounds("sentiment_score", round((composite + 100.0) / 2.0, 1))
        band = _sentiment_band(composite)
        bias = band.lower().replace(" ", "-")
    earnings = _earnings_alert(fundamentals)
    constructive, negative, neutral = _article_tone_counts(articles)
    sample_headlines = [
        (a.get("headline") or "").strip()
        for a in articles
        if (a.get("headline") or "").strip()
    ][:3]

    narrative = _synthesis_paragraph(
        sym,
        band=band,
        score_0_100=score_0_100,
        composite=composite,
        news_score=news_score,
        news_count=news_block["count"],
        constructive=constructive,
        negative=negative,
        neutral=neutral,
        sample_headlines=sample_headlines,
        flow_score=flow.get("score"),
        flow_label=flow.get("label"),
        call_vol=flow.get("call_volume"),
        put_vol=flow.get("put_volume"),
        avg_equity_vol=avg_equity_vol,
        pc_ratio=put_call.get("ratio"),
        pc_label=pc_label,
        pc_score=put_call.get("score"),
        volume_context=volume_context,
        notional_skew=notional_skew,
        renorm=renorm,
        parts={
            "news": news_block["score"],
            "options_flow": flow.get("score"),
            "social": None,
            "put_call": put_call["score"],
        },
        earnings_message=earnings.get("message"),
        news_error=news_err,
    )

    return {
        "title": "Sentiment — news NLP · flow · social · put/call",
        "symbol": sym,
        "score": composite,
        "score_0_100": score_0_100,
        "band": band,
        "bias": bias,
        "weights": WEIGHTS,
        "weights_applied": renorm,
        "components": {
            "news": news_block,
            "options_flow": flow,
            "social": social,
            "put_call": put_call,
        },
        "earnings_alert": earnings,
        "evidence": {
            "article_count": news_block["count"],
            "flow_source": flow.get("source"),
            "put_call_ratio": put_call.get("ratio"),
            "as_of": fetched_at,
        },
        "narrative": narrative,
    }
