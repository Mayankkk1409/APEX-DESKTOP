"""Equity research plan.

Rules come from the Equity Trading Strategy Masterbook (22 pages):
- Page 2 horizons: intraday, swing (two days to several weeks), position.
- Page 12 weight ranges: technical 50–70, fundamental 20–35, sentiment 10–20.
- Page 13 example scorecard: eight components, 0–2 points, act at 11 of 16
  when no veto is present.
- Page 9: do not recommend a short without verified borrow.
- Page 15: a stop is a structure or ATR level, not a guaranteed fill.

The 60/25/15 display weights are the midpoint of those ranges. They are a
design choice, not a tested constant and not a probability of profit.
Missing news is left missing. It is not scored as neutral.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.analysis.layers import EQUITY_SLIDE_LAYERS
from app.analysis.timeframe import horizon_for

# Midpoint of the masterbook ranges. Disclosed on every payload.
DISPLAY_WEIGHTS = {"technical": 0.60, "fundamental": 0.25, "sentiment": 0.15}
SCORECARD_ACT = 11
SCORECARD_MAX = 16


def parse_analyst_ratings(payload: Any) -> list[dict[str, Any]]:
    """Named ratings from a broker payload. Incomplete rows are dropped."""
    rows = _rating_rows(payload)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rating = _text(row, "rating", "recommendation", "action", "meanRating")
        analyst = _text(row, "analyst", "analystName", "name")
        firm = _text(row, "firm", "brokerage", "company", "analystFirm", "researchFirm")
        if not rating or not (analyst or firm):
            continue
        target = _number(row, "priceTarget", "target", "targetPrice", "adjustedPriceTarget")
        parsed.append(
            {
                "analyst": analyst,
                "firm": firm,
                "rating": rating,
                "price_target": target,
                "currency": _text(row, "currency") or ("USD" if target is not None else None),
                "date": _text(row, "date", "ratingDate", "published", "updated"),
                "source": "NASDAQ",
                "url": _text(row, "url", "link", "sourceUrl"),
            }
        )
    dated = [row for row in parsed if row["date"]]
    undated = [row for row in parsed if not row["date"]]
    dated.sort(key=lambda row: str(row["date"]), reverse=True)
    chosen = (dated + undated)[:5]
    return chosen


def score_equity(facts: dict[str, Any]) -> dict[str, Any]:
    """One equity assessment from a frozen fact sheet. Does not place an order."""
    price = _finite(facts.get("price"))
    atr = _finite(facts.get("atr"))
    trend = str(facts.get("trend") or "unknown")
    timeframe = str(facts.get("timeframe") or "1D")
    shares = _finite(facts.get("shares_held")) or 0.0
    bars = int(facts.get("bars") or 0)
    earnings = _parse_day(facts.get("earnings_date"))
    earnings_known = bool(facts.get("earnings_confirmed")) and earnings is not None
    sentiment_score = _finite(facts.get("sentiment_score")) if facts.get("news_count") else None
    fundamental_score = None if facts.get("is_etf") else _finite(facts.get("fundamental_score"))
    technical_score = _finite(facts.get("technical_score"))

    horizon = _horizon(timeframe, trend)
    earnings_inside = bool(earnings_known and earnings and _inside(earnings, horizon["calendar_days"], facts.get("as_of")))
    bull = _scorecard(facts, side="bull", sentiment_score=sentiment_score, earnings_inside=earnings_inside)
    bear = _scorecard(facts, side="bear", sentiment_score=sentiment_score, earnings_inside=earnings_inside)
    direction = _best_direction(bull, bear, trend)
    levels = _levels(price, atr, _finite(facts.get("support")), _finite(facts.get("resistance")), direction)
    action, why = _action(
        facts,
        bull=bull,
        bear=bear,
        shares=shares,
        bars=bars,
        price=price,
        levels=levels,
        earnings_inside=earnings_inside,
        earnings_known=earnings_known,
    )
    scores = _display_scores(technical_score, fundamental_score, sentiment_score, facts, earnings_inside)
    if levels is None:
        levels = _empty_levels(price)
    else:
        levels = dict(levels)
    fit = _fit(direction, levels, bull, bear, shares)
    analysts = list(facts.get("analysts") or [])
    dated = any(row.get("date") for row in analysts)
    return {
        "research_mode": "equity",
        "symbol": facts.get("symbol"),
        "timeframe": timeframe,
        "as_of": facts.get("as_of"),
        "quote_session": facts.get("quote_session") or "unknown",
        "instrument": "etf" if facts.get("is_etf") else "equity",
        "slides": list(EQUITY_SLIDE_LAYERS),
        "action": action,
        "why": why,
        "direction": direction,
        "fit": fit,
        "trend": trend,
        "holds_shares": shares > 0,
        "short_available": False,
        "short_note": "Borrow availability is not on this feed, so a short sale is not recommended.",
        "horizon": horizon,
        "levels": levels,
        "earnings": {
            "date": earnings.isoformat() if earnings_known and earnings else None,
            "confirmed": earnings_known,
            "inside_holding_window": earnings_inside,
            "source": facts.get("earnings_source"),
        },
        "scorecard": {"bull": bull, "bear": bear, "act_at": SCORECARD_ACT, "max": SCORECARD_MAX},
        "scores": scores,
        "weight_policy": (
            "Display weights are the midpoint of the masterbook ranges "
            "(technical 50–70, fundamental 20–35, sentiment 10–20). "
            "The trade gate is the page-13 scorecard, 11 of 16, not this weighted figure. "
            "Neither number is a probability of profit."
        ),
        "risk_profile": facts.get("risk_profile") or "moderate",
        "market": _market_facts(facts),
        "technical_evidence": list(facts.get("technical_evidence") or []),
        "confirmed_patterns": list(facts.get("confirmed_patterns") or []),
        "developing_patterns": list(facts.get("developing_patterns") or []),
        "news": list(facts.get("news") or []),
        "fundamentals_notes": list(facts.get("fundamentals_notes") or []),
        "analysts": analysts,
        "analyst_basis": "Five most recent analyst ratings" if dated else "Named analyst ratings",
        "analyst_note": (
            "These are longer-horizon street targets. They are not this trade's take-profit."
            if analysts
            else "Named analyst ratings were not on the feed. A consensus target, when present, is shown separately and is not a substitute for five named ratings."
        ),
        "consensus": facts.get("consensus"),
        "order_action": None,
    }


def assemble_equity_research(
    *,
    symbol: str,
    timeframe: str,
    as_of: str | None,
    quote: Any,
    bars: list[dict],
    technical: dict[str, Any],
    volume: dict[str, Any],
    fundamentals: dict[str, Any],
    sentiment: dict[str, Any],
    risk_profile: str,
    shares_held: float,
    analysts: list[dict[str, Any]] | None = None,
    provisional_candle: bool = False,
    quality_reason: str | None = None,
) -> dict[str, Any]:
    """Map an existing scan's equity inputs into the research plan. Options flow is ignored."""
    analysis = technical.get("pattern_analysis") if isinstance(technical.get("pattern_analysis"), dict) else {}
    patterns = analysis.get("patterns") if isinstance(analysis.get("patterns"), list) else []
    confirmed = [p for p in patterns if isinstance(p, dict) and p.get("status") == "confirmed"]
    developing = [p for p in patterns if isinstance(p, dict) and p.get("status") == "forming"]
    direction = str(analysis.get("direction") or "neutral")
    trend = "up" if direction == "bullish" or analysis.get("ema_aligned_bullish") else "down" if direction == "bearish" or analysis.get("ema_aligned_bearish") else "flat"
    highs = [float(b["h"]) for b in bars if _finite(b.get("h")) is not None]
    lows = [float(b["l"]) for b in bars if _finite(b.get("l")) is not None]
    closes = [float(b["c"]) for b in bars if _finite(b.get("c")) is not None]
    price = _finite(getattr(quote, "price", None)) or (closes[-1] if closes else None)
    calendar = fundamentals.get("earnings_calendar") if isinstance(fundamentals.get("earnings_calendar"), dict) else {}
    components = sentiment.get("components") if isinstance(sentiment.get("components"), dict) else {}
    news_block = sentiment.get("news") if isinstance(sentiment.get("news"), dict) else {}
    if not news_block and isinstance(components.get("news"), dict):
        news_block = components["news"]
    articles = [a for a in (news_block.get("articles") or []) if isinstance(a, dict)]
    analyst = fundamentals.get("analyst") if isinstance(fundamentals.get("analyst"), dict) else {}
    bid = _finite(getattr(quote, "bid", None))
    ask = _finite(getattr(quote, "ask", None))
    spread = ((ask - bid) / price) if bid is not None and ask is not None and price else None
    evidence = []
    if analysis.get("narrative"):
        evidence.append(str(analysis["narrative"]))
    if technical.get("narrative"):
        evidence.append(str(technical["narrative"]))
    notes = []
    if fundamentals.get("title"):
        notes.append(str(fundamentals.get("title")))
    for card in fundamentals.get("factor_cards") or []:
        if isinstance(card, dict) and card.get("body"):
            notes.append(f"{card.get('title')}: {card.get('body')}")
    facts = {
        "symbol": symbol,
        "timeframe": timeframe,
        "as_of": as_of or getattr(quote, "as_of", None),
        "quote_session": "closed" if getattr(quote, "status", None) == "stale" else "reference",
        "price": price,
        "atr": _atr(highs, lows, closes),
        "support": min(lows[-20:]) if len(lows) >= 5 else None,
        "resistance": max(highs[-20:]) if len(highs) >= 5 else None,
        "trend": trend,
        "volume_ratio": _finite(volume.get("ratio")),
        "technical_score": _finite(analysis.get("score")),
        "sentiment_score": _finite(news_block.get("score")),
        "news_count": len(articles),
        "fundamental_score": _finite(fundamentals.get("score")),
        "fundamental_trend": _fundamental_trend(fundamentals),
        "is_etf": getattr(quote, "expense_ratio", None) is not None,
        "earnings_date": calendar.get("next_date"),
        "earnings_confirmed": bool(calendar.get("next_date")),
        "earnings_source": calendar.get("source"),
        "spread_pct": spread,
        "bars": len(closes),
        "shares_held": shares_held,
        "risk_profile": risk_profile,
        "technical_evidence": evidence[:4],
        "confirmed_patterns": confirmed[:8],
        "developing_patterns": developing[:5],
        "news": [
            {
                "headline": a.get("headline") or a.get("title"),
                "published": a.get("published_at") or a.get("created_at") or a.get("updated_at"),
                "source": a.get("source") or news_block.get("source"),
                "url": a.get("url"),
            }
            for a in articles[:6]
            if a.get("headline") or a.get("title")
        ],
        "fundamentals_notes": notes[:6],
        "analysts": analysts or [],
        "consensus": {
            "label": analyst.get("consensus_label"),
            "price_target": analyst.get("price_target"),
            "low_target": analyst.get("low_target"),
            "high_target": analyst.get("high_target"),
            "buy": analyst.get("buy"),
            "hold": analyst.get("hold"),
            "sell": analyst.get("sell"),
            "source": analyst.get("source"),
            "status": analyst.get("status"),
        }
        if analyst
        else None,
    }
    plan = score_equity(facts)
    if quality_reason:
        plan["action"] = "Insufficient data"
        plan["why"] = quality_reason
        plan["order_action"] = None
    plan["analysis_context"] = {
        "research_mode": "equity",
        "symbol": symbol,
        "interval": timeframe,
        "bar_count": len(bars),
        "warmup_requested": 600,
        "as_of": as_of,
        "last_completed": bars[-1].get("t") if bars else None,
        "provisional_candle": provisional_candle,
        "secondary": [
            {"interval": "1D", "role": "Pivot ladder on the chart only. Share levels use this interval's candles."}
        ] if timeframe not in {"1D", "1W"} else [],
    }
    plan["volume"] = {
        "last": volume.get("last"),
        "average": volume.get("average"),
        "ratio": volume.get("ratio"),
        "regime": volume.get("regime"),
    }
    return plan


def _scorecard(facts: dict[str, Any], *, side: str, sentiment_score: float | None, earnings_inside: bool) -> dict[str, Any]:
    trend = str(facts.get("trend") or "flat")
    aligned = (side == "bull" and trend == "up") or (side == "bear" and trend == "down")
    opposed = (side == "bull" and trend == "down") or (side == "bear" and trend == "up")
    volume = _finite(facts.get("volume_ratio"))
    components: dict[str, int | None] = {
        "market": None,
        "sector": None,
        "structure": 2 if aligned else 0 if opposed else 1,
        "trend": 2 if aligned else 0 if opposed else 1,
        "volume": 2 if volume is not None and volume >= 1.2 and aligned else 0 if volume is not None and volume < 0.8 else 1 if volume is not None else None,
        "fundamentals": _fundamental_points(facts, side),
        "catalyst": 0 if earnings_inside else 1,
        "sentiment": _sentiment_points(sentiment_score, side),
    }
    earned = sum(v for v in components.values() if isinstance(v, int))
    possible = sum(2 for v in components.values() if v is not None)
    return {
        "side": side,
        "points": components,
        "earned": earned,
        "possible": possible,
        "passes": possible > 0 and earned >= round(SCORECARD_ACT / SCORECARD_MAX * possible),
        "missing": [name for name, value in components.items() if value is None],
    }


def _fundamental_points(facts: dict[str, Any], side: str) -> int | None:
    if facts.get("is_etf"):
        return None
    trend = facts.get("fundamental_trend")
    if trend == "improving":
        return 2 if side == "bull" else 0
    if trend == "deteriorating":
        return 0 if side == "bull" else 2
    if facts.get("fundamental_score") is None:
        return None
    return 1


def _sentiment_points(score: float | None, side: str) -> int | None:
    """News lexicon is signed from -100 to 100. No articles means no points."""
    if score is None:
        return None
    if score >= 20:
        return 2 if side == "bull" else 0
    if score <= -20:
        return 2 if side == "bear" else 0
    return 1


def _action(
    facts: dict[str, Any],
    *,
    bull: dict[str, Any],
    bear: dict[str, Any],
    shares: float,
    bars: int,
    price: float | None,
    levels: dict[str, Any] | None,
    earnings_inside: bool,
    earnings_known: bool,
) -> tuple[str, str]:
    if bars < 30 or price is None:
        return "Avoid", "There are not enough bars, or no reference price, to plan an equity trade."
    profile = str(facts.get("risk_profile") or "moderate")
    reward = (levels or {}).get("reward_risk")
    if profile == "conservative" and isinstance(reward, (int, float)) and reward < 2:
        return "Avoid", "The saved risk profile is conservative. This setup pays less than 2 dollars of target for each dollar of risk."
    if earnings_inside and earnings_known:
        return "Avoid", "A confirmed earnings date falls inside the holding window. This is not an earnings-event strategy, so the plan stops."
    if isinstance(reward, (int, float)) and reward < 1:
        return "Avoid", "The target does not clear the risk to the stop, so the reward is not sufficient."
    if bull["passes"] and not bear["passes"]:
        return "Buy", "The bullish scorecard clears the masterbook example gate and the bearish card does not."
    if bear["passes"] and not bull["passes"]:
        if shares > 0:
            return "Sell", "The bearish scorecard clears the gate and the account already holds shares. This is an exit, not a short sale."
        return "Avoid", "The evidence is bearish, but borrow availability is not verified, so this is not a short sale."
    if shares > 0:
        return "Hold", "The bullish and bearish evidence do not separate cleanly. The existing holding stays a hold."
    return "Avoid", "No actionable setup. The scorecard does not clear 11 of 16 on one side without a conflict."


def _best_direction(bull: dict[str, Any], bear: dict[str, Any], trend: str) -> str:
    """The side that clears the card, otherwise the side with more points, otherwise the trend."""
    if bull.get("passes") and not bear.get("passes"):
        return "long"
    if bear.get("passes") and not bull.get("passes"):
        return "down"
    bull_pts = int(bull.get("earned") or 0)
    bear_pts = int(bear.get("earned") or 0)
    if bear_pts > bull_pts:
        return "down"
    if bull_pts > bear_pts:
        return "long"
    return "down" if trend == "down" else "long"


def _fit(
    direction: str,
    levels: dict[str, Any],
    bull: dict[str, Any],
    bear: dict[str, Any],
    shares: float,
) -> str:
    cards = (
        f"The bullish card is {bull.get('earned')} of {bull.get('possible')}. "
        f"The bearish card is {bear.get('earned')} of {bear.get('possible')}. "
    )
    entry = levels.get("entry")
    stop = levels.get("stop")
    target = levels.get("take_profit")
    reward = levels.get("reward_risk")
    if not isinstance(entry, (int, float)) or not isinstance(stop, (int, float)) or not isinstance(target, (int, float)):
        return cards + "The levels need a reference price before the stop and the target can be placed."
    payoff = f" The target pays {reward:.2f} dollars for each dollar of risk." if isinstance(reward, (int, float)) else ""
    if direction == "down":
        held = (
            " The account already holds shares, so the order that matches this case is a sale of those shares."
            if shares > 0
            else " Borrow is not on this feed, so no short sale is sent. These levels are still the downside case, because that is the side that fits."
        )
        return (
            f"{cards}The downside case is the one that fits. It pays if the share falls from {entry:.2f}. "
            f"The stop at {stop:.2f} is above the entry, because a rise through it means the decline failed. "
            f"The take-profit at {target:.2f} is below the entry, because that is the lower objective.{payoff}{held}"
        )
    return (
        f"{cards}The upside case is the one that fits. It pays if the share rises from {entry:.2f}. "
        f"The stop at {stop:.2f} is below the entry, because a drop through it means the rise failed. "
        f"The take-profit at {target:.2f} is above the entry, because that is the higher objective.{payoff}"
    )


def _levels(price: float | None, atr: float | None, support: float | None, resistance: float | None, direction: str) -> dict[str, Any] | None:
    """Place the stop and the target on the side the stronger case needs."""
    if price is None or price <= 0:
        return None
    risk = atr if atr and atr > 0 else price * 0.02
    risk_basis = "14-bar average true range" if atr and atr > 0 else "2% of price because ATR is unavailable"
    entry = round(price, 2)
    if direction == "down":
        stop = round(price + risk, 2)
        target = round(support, 2) if support and support < price - risk else round(price - 2 * risk, 2)
        exit_note = "Downside case. The stop is above the entry and the take-profit is below it."
    else:
        stop = round(max(0.01, price - risk), 2)
        target = round(resistance, 2) if resistance and resistance > price + risk else round(price + 2 * risk, 2)
        exit_note = "Upside case. The stop is below the entry and the take-profit is above it."
    reward = abs(target - entry)
    risk_amt = abs(entry - stop)
    return {
        "entry": entry,
        "entry_label": "Reference price on this snapshot. It is the price the case is measured from, not a filled order.",
        "stop": stop,
        "stop_basis": risk_basis,
        "take_profit": target,
        "exit_target": target,
        "exit_note": exit_note,
        "reward_risk": round(reward / risk_amt, 2) if risk_amt else None,
        "reference": "snapshot",
    }


def _empty_levels(price: float | None) -> dict[str, Any]:
    return {
        "entry": round(price, 2) if price else None,
        "entry_label": "No order levels are proposed.",
        "stop": None,
        "take_profit": None,
        "exit_target": None,
        "exit_note": "Hold and Avoid do not invent a target.",
        "reward_risk": None,
    }


def _display_scores(
    technical: float | None,
    fundamental: float | None,
    sentiment: float | None,
    facts: dict[str, Any],
    earnings_inside: bool,
) -> dict[str, Any]:
    risk = _risk_score(facts, earnings_inside)
    # The news lexicon is signed from -100 to 100. The pillar uses the same 0–100 scale as technicals.
    sentiment_display = None if sentiment is None else round((max(-100.0, min(100.0, sentiment)) + 100.0) / 2, 1)
    parts = [("technical", DISPLAY_WEIGHTS["technical"], technical), ("fundamental", DISPLAY_WEIGHTS["fundamental"], fundamental), ("sentiment", DISPLAY_WEIGHTS["sentiment"], sentiment_display)]
    used = [(name, weight, score) for name, weight, score in parts if score is not None]
    weight_sum = sum(weight for _, weight, _ in used)
    overall = round(sum(weight / weight_sum * score for _, weight, score in used), 1) if weight_sum else None
    return {
        "technical": technical,
        "sentiment": sentiment_display,
        "fundamental": fundamental,
        "risk": risk,
        "overall": overall,
        "reweighted": [name for name, _, score in parts if score is None],
        "contributions": [
            {"layer": name, "weight": round(weight / weight_sum, 4), "score": score, "points": round(weight / weight_sum * score, 2)}
            for name, weight, score in used
        ],
    }


def _market_facts(facts: dict[str, Any]) -> dict[str, Any]:
    price = _finite(facts.get("price"))
    atr = _finite(facts.get("atr"))
    spread = _finite(facts.get("spread_pct"))
    support = _finite(facts.get("support"))
    resistance = _finite(facts.get("resistance"))
    return {
        "price": round(price, 2) if price else None,
        "atr": round(atr, 4) if atr else None,
        "atr_pct": round(atr / price * 100, 2) if atr and price and price > 0 else None,
        "spread_pct": round(spread * 100, 2) if spread is not None else None,
        "support": round(support, 2) if support else None,
        "resistance": round(resistance, 2) if resistance else None,
    }


def _risk_score(facts: dict[str, Any], earnings_inside: bool) -> float | None:
    atr = _finite(facts.get("atr"))
    price = _finite(facts.get("price"))
    if atr is None or price is None or price <= 0:
        return None
    atr_pct = atr / price
    score = 80.0 if atr_pct <= 0.02 else 60.0 if atr_pct <= 0.04 else 40.0
    if earnings_inside:
        score -= 25
    spread = _finite(facts.get("spread_pct"))
    if spread is not None and spread > 0.01:
        score -= 10
    return round(max(0.0, min(100.0, score)), 1)


def _horizon(timeframe: str, trend: str) -> dict[str, Any]:
    """The options timeframe table names the use. A flat trend does not replace that interval."""
    _ = trend
    return horizon_for(timeframe)


def _inside(event: date, window_days: int, as_of: Any) -> bool:
    start = _parse_day(as_of) or date.today()
    return 0 <= (event - start).days <= window_days


def _fundamental_trend(fundamentals: dict[str, Any]) -> str | None:
    surprise = fundamentals.get("earnings_surprise") if isinstance(fundamentals.get("earnings_surprise"), dict) else {}
    trend = surprise.get("trend")
    if trend == "consecutive_beats":
        return "improving"
    if trend == "mixed":
        return "deteriorating"
    if fundamentals.get("score") is None:
        return None
    return "neutral"


def _atr(highs: list[float], lows: list[float], closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    ranges: list[float] = []
    for i in range(1, len(closes)):
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    sample = ranges[-14:]
    if not sample:
        return None
    return round(sum(sample) / len(sample), 4)


def _rating_rows(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return []
    for key in ("rows", "ratings", "analystRatings"):
        found = data.get(key)
        if isinstance(found, list):
            return found
        if isinstance(found, dict) and isinstance(found.get("rows"), list):
            return found["rows"]
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("rows"), list):
            return value["rows"]
    return []


def _text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _finite(row.get(key))
        if value is not None:
            return value
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _parse_day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
