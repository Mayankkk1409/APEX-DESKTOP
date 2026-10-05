from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Order, Position
from app.models.user import User
from app.services.executability import (
    DEFAULT_SPREAD_MAX,
    load_submission_quote,
    marketable_limit,
    slippage_dollars,
    spread_confirmation_text,
    spread_vs_mid,
)
from app.services.occ_symbol import parse_occ
from app.services.orders import account_impact, estimate_order_cost
from app.strategies.registry import get_strategy_spec, resolve_strategy_id
from app.strategies.validator import validate_strategy_output
from app.ws.hub import hub


def position_multiplier(asset_class: str) -> int:
    return 100 if asset_class == "us_option" else 1


_REJECTED_STATUSES = {"rejected", "canceled", "cancelled", "expired", "failed", "suspended", "error"}


def _broker_rejected(broker: object) -> bool:
    if not isinstance(broker, dict):
        return True
    if broker.get("rejected") is True:
        return True
    return str(broker.get("status") or "").lower() in _REJECTED_STATUSES


# Alpaca refuses option market orders when the session is closed. A paper account
# can still fill on the local book. A buying-power or contract rejection cannot.
_SESSION_PAPER_MARKERS = (
    "options market orders are only allowed during market hours",
    "market orders are only allowed during market hours",
    "market is closed",
    "outside of market hours",
    "outside market hours",
)


def _broker_reason(broker: dict) -> str:
    reason = broker.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return "Broker rejected the order"


def _session_restricted(reason: str) -> bool:
    text = reason.lower()
    return any(marker in text for marker in _SESSION_PAPER_MARKERS)


def _positive_mark(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 0:
        return value
    return None


def _option_quote_is_equity_fallback(symbol: str, quote: object) -> bool:
    """A stock feed cannot price an OCC symbol. The demo fallback looks like a $100 share."""
    if parse_occ(symbol) is None:
        return False
    source = str(getattr(quote, "source", "") or "").lower()
    asset = str(getattr(quote, "asset_class", "") or "").lower()
    if asset in {"us_option", "option"}:
        return False
    return source in {"demo", "unavailable", ""} or "demo" in source


async def _paper_submit(payload: dict[str, Any]) -> dict:
    """Existing demo/paper fill used when Alpaca is dark, closed, or rejects."""
    from app.adapters.demo import DemoAdapter

    return await DemoAdapter().submit_order(**payload)


async def _submit_for_fill(
    adapter: Any,
    *,
    force_paper: bool,
    symbol: str,
    qty: float,
    side: str,
    order_type: str,
    limit_price: float | None,
    strict: bool = False,
    session_paper: bool = False,
) -> dict:
    payload = {
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "order_type": order_type,
        "limit_price": limit_price,
        "strict": strict,
    }
    if force_paper:
        return await _paper_submit(payload)
    try:
        broker = await adapter.submit_order(**payload)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).strip() or "Broker order failed"
        if strict and not (session_paper and _session_restricted(reason)):
            raise ValueError(reason) from exc
        logger.warning("Broker order failed ({}); using paper fill", type(exc).__name__)
        paper = await _paper_submit(payload)
        if _session_restricted(reason):
            paper["session_paper_fill"] = True
        return paper
    if not isinstance(broker, dict) or _broker_rejected(broker):
        reason = _broker_reason(broker) if isinstance(broker, dict) else "Broker rejected the order"
        if strict and not (session_paper and _session_restricted(reason)):
            raise ValueError(reason)
        if strict:
            logger.warning("Broker order rejected ({}); using paper fill", reason)
        else:
            logger.warning("Broker order rejected; using paper fill")
        paper = await _paper_submit(payload)
        if _session_restricted(reason):
            paper["session_paper_fill"] = True
        return paper
    return broker


async def refresh_portfolio_value(user: User, db: AsyncSession, adapter: Any) -> float:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    live_value = user.cash_balance
    for pos in positions:
        q = await adapter.quote(pos.symbol)
        if q.price is not None and not _option_quote_is_equity_fallback(pos.symbol, q):
            pos.current_price = q.price
        mult = position_multiplier(pos.asset_class)
        live_value += pos.qty * pos.current_price * mult
    user.portfolio_value = round(live_value, 2)
    user.buying_power = user.cash_balance
    return user.portfolio_value


async def execute_market_fill(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    symbol: str,
    side: str,
    qty: float,
    asset_class: str = "us_equity",
    order_type: str = "market",
    limit_price: float | None = None,
    scan_id: str | None = None,
    strategy_name: str | None = None,
    certificate: dict[str, Any] | None = None,
    force_paper: bool = False,
    closing: bool = False,
    strict: bool = False,
    mark_price: float | None = None,
    routing: dict[str, Any] | None = None,
    spread_confirmed: bool = False,
    spread_max: float = DEFAULT_SPREAD_MAX,
    submission_path: str = "market_fill",
    skip_quote_check: bool = False,
) -> Order:
    if not skip_quote_check:
        from app.services.executability import enforce_submission_quotes, marketable_limit

        await enforce_submission_quotes(
            adapter,
            [symbol],
            path=submission_path,
            spread_confirmed=spread_confirmed,
            contracts=qty,
            multiplier=position_multiplier(asset_class),
            spread_max=spread_max,
        )
        if asset_class == "us_option":
            quote = await adapter.quote(symbol)
            live = marketable_limit(side, quote)
            live_limit = live[0] if live is not None else None
            if live_limit is not None:
                order_type = "limit"
                limit_price = live_limit
            elif order_type != "limit":
                order_type = "limit"
                if limit_price is None:
                    limit_price = _positive_mark(getattr(quote, "price", None))
    mark = _positive_mark(mark_price)
    if asset_class == "us_option" and mark is not None:
        px = mark
    else:
        quote = await adapter.quote(symbol)
        px = limit_price if order_type == "limit" and limit_price is not None else quote.price
    if px is None:
        raise ValueError("Live quote unavailable for this symbol")
    mult = position_multiplier(asset_class)
    cost = estimate_order_cost(qty, px, asset_class=asset_class, multiplier=mult)  # type: ignore[arg-type]
    impact = account_impact(side, cost)
    if side == "buy" and cost > user.buying_power and not closing:
        raise ValueError("Insufficient buying power")

    order = Order(
        user_id=user.id,
        scan_id=scan_id,
        symbol=symbol.upper(),
        side=side,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
        estimated_cost=cost,
        asset_class=asset_class,
        multiplier=mult,
        status="accepted",
    )
    db.add(order)
    await db.flush()

    broker = await _submit_for_fill(
        adapter,
        force_paper=force_paper,
        symbol=order.symbol,
        qty=order.qty,
        side=order.side,
        order_type=order.order_type,
        limit_price=order.limit_price,
        strict=strict,
        session_paper=user.account_mode != "real_brokerage",
    )
    if routing is not None and isinstance(broker, dict) and broker.get("session_paper_fill"):
        routing["force_paper"] = True
    fill_px = float(broker.get("filled_avg_price") or px)
    order.status = "filled"
    order.fill_price = fill_px
    order.filled_at = datetime.now(timezone.utc)

    pos = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == order.symbol))
    signed = order.qty if order.side == "buy" else -order.qty
    if pos:
        new_qty = pos.qty + signed
        if new_qty == 0:
            await db.delete(pos)
        elif order.side == "buy":
            pos.avg_cost = (pos.avg_cost * pos.qty + fill_px * order.qty) / new_qty
            pos.qty = new_qty
            pos.current_price = fill_px
            if strategy_name and not pos.strategy_name:
                pos.strategy_name = strategy_name
            if certificate and not pos.certificate:
                pos.certificate = certificate
        else:
            pos.qty = new_qty
            pos.current_price = fill_px
    elif order.side == "buy" or (order.side == "sell" and asset_class == "us_option"):
        opened = order.qty if order.side == "buy" else -order.qty
        db.add(
            Position(
                user_id=user.id,
                symbol=order.symbol,
                qty=opened,
                avg_cost=fill_px,
                current_price=fill_px,
                asset_class=asset_class,
                strategy_name=strategy_name,
                certificate=certificate,
            )
        )

    user.cash_balance = round(user.cash_balance + impact, 2)
    await refresh_portfolio_value(user, db, adapter)
    await db.commit()
    await db.refresh(order)

    await hub.broadcast(
        user.id,
        {
            "type": "fill",
            "order_id": order.id,
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "price": fill_px,
            "asset_class": order.asset_class,
            "balance": user.cash_balance,
            "buying_power": user.buying_power,
            "portfolio_value": user.portfolio_value,
        },
    )
    return order


async def execute_strategy_legs(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    legs: list[dict[str, Any]],
    scan_id: str | None = None,
    contracts_per_leg: float = 1,
    strategy_name: str | None = None,
    certificate: dict[str, Any] | None = None,
    equity_legs: list[dict[str, Any]] | None = None,
    equity_satisfied: bool = False,
    checks_passed: bool | None = None,
    auto_execute: bool = False,
    spread_confirmed: bool = False,
    spread_max: float = DEFAULT_SPREAD_MAX,
    submission_path: str = "strategy_legs",
    wide_spread_only: bool = False,
) -> list[Order]:
    """Fill stock first, then options. A short call is sent only after covering shares are in place."""
    from app.analysis.gate_config import refuse_if_checks_failed
    from app.services.executability import enforce_submission_quotes, order_symbols
    from app.services.stock_leg import SHORT_STOCK_INFEASIBLE, is_short_call, partition_option_legs

    if checks_passed is False and not (wide_spread_only and spread_confirmed):
        try:
            refuse_if_checks_failed(checks_passed=checks_passed, auto_execute=auto_execute)
        except ValueError as exc:
            logger.warning("order blocked reason={}", exc)
            raise
    await enforce_submission_quotes(
        adapter,
        order_symbols(legs, *[str((row or {}).get("symbol") or "") for row in (equity_legs or [])]),
        path=submission_path,
        spread_confirmed=spread_confirmed,
        contracts=contracts_per_leg,
        spread_max=spread_max,
    )
    if not legs and not equity_legs:
        raise ValueError("Strategy legs are required for execution")
    if strategy_name and certificate:
        metrics = {
            "legs": certificate.get("legs") or legs,
            "max_profit": certificate.get("max_profit"),
            "max_loss": certificate.get("max_loss"),
            "breakevens": certificate.get("breakevens") or [],
        }
        ticker = str(certificate.get("symbol") or "")
        if not ticker and legs:
            occ = str(legs[0].get("symbol") or "")
            ticker = occ[: occ.find(next((c for c in occ if c.isdigit()), ""))] if occ else "—"
        validation = validate_strategy_output(
            strategy_name,
            metrics,
            ticker or "—",
            order_legs=legs,
        )
        if not validation.valid:
            err = validation.errors[0]
            raise ValueError(str(err))
        spec = get_strategy_spec(strategy_name)
        if spec and spec.equity_required and spec.equity_leg_spec:
            if not equity_legs and not equity_satisfied:
                raise ValueError("Equity-required strategy missing stock leg — execution blocked")
        elif equity_legs:
            raise ValueError("Equity legs submitted for options-only strategy — execution blocked")
    qty = contracts_per_leg
    if qty <= 0:
        raise ValueError("contracts_per_leg must be positive")
    buys, shorts = partition_option_legs(legs)
    # One symbol per request. Buys fill before any short option. A rejected component stops the rest of the shorts.
    strict = bool(equity_legs) or bool(shorts) or equity_satisfied
    orders: list[Order] = []
    routing: dict[str, Any] = {"force_paper": False}
    marks = _premium_marks(list((certificate or {}).get("legs") or []), list(legs))

    def _option_limit(leg: dict[str, Any]) -> tuple[str, float | None]:
        kind = str(leg.get("order_type") or "market").lower()
        if kind != "limit":
            return "market", None
        raw = leg.get("limit_price")
        if raw is None:
            raw = leg.get("price") if leg.get("price") is not None else leg.get("mid")
        try:
            price = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None or price <= 0:
            raise ValueError("Live mid is unavailable, so a limit at mid cannot be priced.")
        return "limit", price

    async def _fill_one(
        *,
        symbol: str,
        side: str,
        leg_qty: float,
        asset_class: str,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> Order:
        use_paper = bool(routing["force_paper"])
        return await execute_market_fill(
            user=user,
            db=db,
            adapter=adapter,
            symbol=symbol,
            side=side,
            qty=leg_qty,
            asset_class=asset_class,
            order_type=order_type,
            limit_price=limit_price,
            scan_id=scan_id,
            strategy_name=strategy_name,
            certificate=certificate,
            force_paper=use_paper,
            strict=strict and not use_paper,
            mark_price=marks.get(symbol) if asset_class == "us_option" else None,
            routing=routing,
            spread_confirmed=spread_confirmed,
            spread_max=spread_max,
        )

    def _holdback(exc: Exception, *, short_leg: bool) -> ValueError:
        reason = str(exc).strip() or "Option or stock order failed"
        if reason[-1] not in ".!?":
            reason = f"{reason}."
        if short_leg:
            safety = "Remaining short legs were not submitted."
        elif any(is_short_call(leg) for leg in shorts):
            safety = "The short call was not submitted. Remaining short legs were not submitted."
        else:
            safety = "Remaining short legs were not submitted."
        if safety in reason:
            return ValueError(reason)
        return ValueError(f"{reason} {safety}")

    for eq in equity_legs or []:
        if str(eq.get("side") or "").lower() == "sell":
            raise ValueError(SHORT_STOCK_INFEASIBLE)

    try:
        for eq in equity_legs or []:
            symbol = str(eq.get("symbol") or "").upper()
            side = str(eq.get("side") or "").lower()
            eq_qty = float(eq.get("qty") or 0)
            if not symbol or side not in {"buy", "sell"} or eq_qty <= 0:
                raise ValueError("Each equity leg must include a ticker symbol, buy/sell side, and share quantity")
            order = await _fill_one(symbol=symbol, side=side, leg_qty=eq_qty, asset_class="us_equity")
            if order.status != "filled":
                raise ValueError("Stock leg did not fill")
            orders.append(order)
        if len(legs) >= 2:
            for leg in legs:
                symbol = str(leg.get("symbol") or "").upper()
                if _leg_premium(leg, marks) is None and symbol:
                    quote = await adapter.quote(symbol)
                    price = getattr(quote, "price", None)
                    if (
                        isinstance(price, (int, float))
                        and not isinstance(price, bool)
                        and price > 0
                        and not _option_quote_is_equity_fallback(symbol, quote)
                    ):
                        marks[symbol] = float(price)
            orders.append(
                await _execute_combo(
                    user=user,
                    db=db,
                    adapter=adapter,
                    legs=list(legs),
                    qty=qty,
                    scan_id=scan_id,
                    strategy_name=strategy_name,
                    certificate=certificate,
                    marks=marks,
                    spread_confirmed=spread_confirmed,
                    spread_max=spread_max,
                )
            )
            return orders
        for leg in buys:
            occ = str(leg.get("symbol") or "").upper()
            side = str(leg.get("side") or "").lower()
            if not occ or side not in {"buy", "sell"}:
                raise ValueError("Each leg must include an OCC symbol and buy/sell side")
            order_type, limit_price = _option_limit(leg)
            orders.append(
                await _fill_one(
                    symbol=occ,
                    side=side,
                    leg_qty=qty,
                    asset_class="us_option",
                    order_type=order_type,
                    limit_price=limit_price,
                )
            )
    except Exception as exc:
        if shorts:
            raise _holdback(exc, short_leg=False) from exc
        raise
    for leg in shorts:
        occ = str(leg.get("symbol") or "").upper()
        side = str(leg.get("side") or "").lower()
        if not occ or side not in {"buy", "sell"}:
            raise ValueError("Each leg must include an OCC symbol and buy/sell side")
        try:
            order_type, limit_price = _option_limit(leg)
            orders.append(
                await _fill_one(
                    symbol=occ,
                    side=side,
                    leg_qty=qty,
                    asset_class="us_option",
                    order_type=order_type,
                    limit_price=limit_price,
                )
            )
        except Exception as exc:
            raise _holdback(exc, short_leg=True) from exc
    return orders


def _leg_side(leg: dict[str, Any]) -> str:
    action = str(leg.get("side") or leg.get("action") or "").lower()
    return action if action in {"buy", "sell"} else ""


def _leg_premium(leg: dict[str, Any], marks: dict[str, float]) -> float | None:
    for key in ("limit_price", "price", "mid", "mark"):
        mark = _positive_mark(leg.get(key))
        if mark is not None:
            return mark
    symbol = str(leg.get("symbol") or "").upper()
    if symbol and symbol in marks:
        return marks[symbol]
    return None


def _combo_symbol(legs: list[dict[str, Any]]) -> str:
    roots: list[str] = []
    for leg in legs:
        parsed = parse_occ(str(leg.get("symbol") or ""))
        if parsed is not None:
            roots.append(parsed.root)
    if roots and len(set(roots)) == 1:
        return roots[0][:32]
    return "COMBO"


def combo_net_mid(legs: list[dict[str, Any]], marks: dict[str, float]) -> float:
    """Signed premium for one combo. Positive is a debit, negative is a credit."""
    net = 0.0
    for leg in legs:
        premium = _leg_premium(leg, marks)
        if premium is None:
            symbol = leg.get("symbol") or leg.get("side") or "option"
            raise ValueError(f"Live mid is unavailable, so a limit at the net mid cannot be priced for {symbol}.")
        sign = 1.0 if _leg_side(leg) == "buy" else -1.0
        net += sign * premium
    return round(net, 2)


async def _open_combo_positions(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    legs: list[dict[str, Any]],
    qty: float,
    marks: dict[str, float],
    strategy_name: str | None,
    certificate: dict[str, Any] | None,
    order: Order,
    cash_impact: float,
) -> None:
    for leg in legs:
        symbol = str(leg.get("symbol") or "").upper()
        side = _leg_side(leg)
        fill_px = _leg_premium(leg, marks)
        if not symbol or side not in {"buy", "sell"} or fill_px is None:
            continue
        pos = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == symbol))
        signed = qty if side == "buy" else -qty
        if pos:
            new_qty = pos.qty + signed
            if new_qty == 0:
                await db.delete(pos)
            elif side == "buy":
                pos.avg_cost = (pos.avg_cost * pos.qty + fill_px * qty) / new_qty
                pos.qty = new_qty
                pos.current_price = fill_px
                if strategy_name and not pos.strategy_name:
                    pos.strategy_name = strategy_name
                if certificate and not pos.certificate:
                    pos.certificate = certificate
            else:
                pos.qty = new_qty
                pos.current_price = fill_px
        else:
            db.add(
                Position(
                    user_id=user.id,
                    symbol=symbol,
                    qty=signed,
                    avg_cost=fill_px,
                    current_price=fill_px,
                    asset_class="us_option",
                    strategy_name=strategy_name,
                    certificate=certificate,
                )
            )
    user.cash_balance = round(user.cash_balance + cash_impact, 2)
    await refresh_portfolio_value(user, db, adapter)
    await db.commit()
    await db.refresh(order)
    await hub.broadcast(
        user.id,
        {
            "type": "fill",
            "order_id": order.id,
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "price": order.fill_price,
            "asset_class": order.asset_class,
            "balance": user.cash_balance,
            "buying_power": user.buying_power,
            "portfolio_value": user.portfolio_value,
            "combo": True,
        },
    )


async def _execute_combo(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    legs: list[dict[str, Any]],
    qty: float,
    scan_id: str | None,
    strategy_name: str | None,
    certificate: dict[str, Any] | None,
    marks: dict[str, float],
    spread_confirmed: bool = False,
    spread_max: float = DEFAULT_SPREAD_MAX,
) -> Order:
    """One limit combo at the net mid. A rejection is not split into market orders."""
    net = combo_net_mid(legs, marks)
    side = "buy" if net >= 0 else "sell"
    limit = round(abs(net), 2)
    combo_symbol = _combo_symbol(legs)
    broker_legs = []
    for leg in legs:
        occ = str(leg.get("symbol") or "").upper()
        leg_side = _leg_side(leg)
        if not occ or leg_side not in {"buy", "sell"}:
            raise ValueError("Each leg must include an OCC symbol and buy/sell side")
        broker_legs.append(
            {
                "symbol": occ,
                "side": leg_side,
                "ratio_qty": 1,
                "position_intent": "buy_to_open" if leg_side == "buy" else "sell_to_open",
            }
        )
    mult = position_multiplier("us_option")
    cost = estimate_order_cost(qty, limit, asset_class="us_option", multiplier=mult)
    if side == "buy" and cost > user.buying_power:
        raise ValueError("Insufficient buying power. No short leg was submitted.")

    payload = {
        "symbol": combo_symbol,
        "qty": qty,
        "side": side,
        "order_type": "limit",
        "limit_price": net,
        "order_class": "mleg",
        "legs": broker_legs,
        "strict": True,
    }
    session_paper = user.account_mode != "real_brokerage"

    async def _reject(reason: str) -> None:
        text = reason.strip() or "Broker cannot accept a combo order"
        if text[-1] not in ".!?":
            text = f"{text}."
        raise ValueError(
            f"{text} The combo was not split into market orders. No short leg was submitted."
        )

    try:
        broker = await adapter.submit_order(**payload)
    except TypeError as exc:
        raise ValueError(
            "Broker cannot accept a combo order. The combo was not split into market orders. No short leg was submitted."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).strip() or "Broker order failed"
        if session_paper and _session_restricted(reason):
            broker = {"session_paper_fill": True, "status": "rejected", "reason": reason}
        else:
            await _reject(reason)
            raise
    if not isinstance(broker, dict) or _broker_rejected(broker):
        reason = _broker_reason(broker) if isinstance(broker, dict) else "Broker rejected the order"
        if not (session_paper and _session_restricted(reason)):
            await _reject(reason)
        fill_px = limit
    else:
        raw_fill = broker.get("filled_avg_price")
        fill_px = abs(float(raw_fill)) if _positive_mark(raw_fill) is not None else limit

    order = Order(
        user_id=user.id,
        scan_id=scan_id,
        symbol=combo_symbol,
        side=side,
        qty=qty,
        order_type="limit",
        limit_price=limit,
        estimated_cost=cost,
        asset_class="us_option",
        multiplier=mult,
        status="filled",
        fill_price=fill_px,
        filled_at=datetime.now(timezone.utc),
    )
    db.add(order)
    await db.flush()
    await _open_combo_positions(
        user=user,
        db=db,
        adapter=adapter,
        legs=legs,
        qty=qty,
        marks=marks,
        strategy_name=strategy_name,
        certificate=certificate,
        order=order,
        cash_impact=account_impact(side, estimate_order_cost(qty, fill_px, asset_class="us_option", multiplier=mult)),
    )
    return order


def _premium_marks(*groups: list[dict[str, Any]]) -> dict[str, float]:
    """Chain premium by OCC symbol. The first positive mark wins, so the stored scan mid beats a later copy."""
    marks: dict[str, float] = {}
    for group in groups:
        for leg in group:
            if not isinstance(leg, dict):
                continue
            symbol = str(leg.get("symbol") or "").upper()
            if not symbol or symbol in marks:
                continue
            for key in ("mid", "price", "mark"):
                mark = _positive_mark(leg.get(key))
                if mark is not None:
                    marks[symbol] = mark
                    break
    return marks
