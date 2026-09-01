from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from app.models.trading import Order, Position
from app.models.user import User
from app.services.fills import position_multiplier


def account_baseline(user: User) -> float:
    """Paper = chosen starting balance; real = balance captured at connect (or signup cash)."""
    if user.account_mode == "paper_funded":
        return float(user.starting_balance or user.cash_balance or 0)
    return float(user.starting_balance if user.starting_balance is not None else user.cash_balance or 0)


@dataclass
class _Book:
    qty: float = 0.0
    avg_cost: float = 0.0
    asset_class: str = "us_equity"
    realized_pl: float = 0.0


@dataclass
class SymbolPnlRow:
    symbol: str
    asset_class: str
    qty: float
    realized_pl: float
    unrealized_pl: float
    total_pl: float
    is_open: bool


def _as_utc(dt: datetime) -> datetime:
    """SQLite often stores naive timestamps; normalize before comparing."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _order_ts(order: Order) -> datetime:
    raw = order.filled_at or order.created_at
    if raw is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return _as_utc(raw)


def replay_filled_orders(orders: list[Order]) -> dict[str, _Book]:
    books: dict[str, _Book] = {}
    filled = [o for o in orders if o.status == "filled" and o.fill_price is not None]
    filled.sort(key=_order_ts)
    for order in filled:
        sym = order.symbol.upper()
        book = books.setdefault(sym, _Book(asset_class=order.asset_class))
        book.asset_class = order.asset_class
        mult = position_multiplier(order.asset_class)
        px = float(order.fill_price)
        if order.side == "buy":
            if book.qty > 0:
                book.avg_cost = (book.avg_cost * book.qty + px * order.qty) / (book.qty + order.qty)
            else:
                book.avg_cost = px
            book.qty += order.qty
        else:
            sell_qty = min(order.qty, book.qty) if book.qty > 0 else order.qty
            if sell_qty > 0 and book.qty > 0:
                book.realized_pl += (px - book.avg_cost) * sell_qty * mult
                book.qty -= sell_qty
                if book.qty == 0:
                    book.avg_cost = 0.0
    return books


def symbol_pnl_rows(orders: list[Order], positions: list[Position]) -> list[SymbolPnlRow]:
    books = replay_filled_orders(orders)
    pos_by_sym = {p.symbol.upper(): p for p in positions}
    symbols = set(books) | set(pos_by_sym)
    rows: list[SymbolPnlRow] = []
    for sym in sorted(symbols):
        book = books.get(sym, _Book())
        pos = pos_by_sym.get(sym)
        asset_class = pos.asset_class if pos else book.asset_class
        mult = position_multiplier(asset_class)
        qty = pos.qty if pos else book.qty
        unrealized = 0.0
        if pos and pos.qty > 0:
            unrealized = (pos.current_price - pos.avg_cost) * pos.qty * mult
        realized = book.realized_pl
        rows.append(
            SymbolPnlRow(
                symbol=sym,
                asset_class=asset_class,
                qty=qty,
                realized_pl=round(realized, 2),
                unrealized_pl=round(unrealized, 2),
                total_pl=round(realized + unrealized, 2),
                is_open=bool(pos and pos.qty > 0),
            )
        )
    return rows


def _utc_date(dt: datetime) -> date:
    return _as_utc(dt).date()


def _day_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _replay_equity_events(
    user: User,
    orders: list[Order],
    positions: list[Position],
    baseline: float,
) -> list[tuple[datetime, float]]:
    """Portfolio equity after each fill and at the live mark."""
    events: list[tuple[datetime, float]] = []
    cash = baseline
    open_lots: dict[str, _Book] = {}
    filled = [o for o in orders if o.status == "filled" and o.fill_price is not None]
    filled.sort(key=_order_ts)

    for order in filled:
        sym = order.symbol.upper()
        px = float(order.fill_price)
        mult = position_multiplier(order.asset_class)
        cost = round(order.qty * px * mult, 2)
        lot = open_lots.setdefault(sym, _Book(asset_class=order.asset_class))
        lot.asset_class = order.asset_class

        if order.side == "buy":
            cash -= cost
            if lot.qty > 0:
                lot.avg_cost = (lot.avg_cost * lot.qty + px * order.qty) / (lot.qty + order.qty)
            else:
                lot.avg_cost = px
            lot.qty += order.qty
        else:
            cash += cost
            lot.qty = max(0.0, lot.qty - order.qty)
            if lot.qty == 0:
                lot.avg_cost = 0.0

        marked = 0.0
        for s, l in open_lots.items():
            if l.qty <= 0:
                continue
            mark = px if s == sym else l.avg_cost
            marked += l.qty * mark * position_multiplier(l.asset_class)

        portfolio_value = round(cash + marked, 2)
        ts = _order_ts(order)
        events.append((ts, portfolio_value))

    live_cash = user.cash_balance
    live_holdings = 0.0
    for pos in positions:
        mult = position_multiplier(pos.asset_class)
        live_holdings += pos.qty * pos.current_price * mult
    live_value = round(live_cash + live_holdings, 2)
    now = datetime.now(timezone.utc)
    if not events or events[-1][1] != live_value or _utc_date(events[-1][0]) < _utc_date(now):
        events.append((now, live_value))
    return events


def pnl_history_points(user: User, orders: list[Order], positions: list[Position]) -> list[dict]:
    """Daily account equity from account creation through today."""
    baseline = account_baseline(user)
    account_start = _as_utc(user.created_at) if user.created_at else datetime.now(timezone.utc)
    filled = [o for o in orders if o.status == "filled" and o.fill_price is not None]

    range_start = _utc_date(account_start)
    if filled:
        earliest_fill = min(_order_ts(o) for o in filled)
        range_start = min(range_start, _utc_date(earliest_fill))

    today = _utc_date(datetime.now(timezone.utc))
    events = _replay_equity_events(user, orders, positions, baseline)

    points: list[dict] = []
    current_value = baseline
    event_idx = 0
    day = range_start
    while day <= today:
        day_end = _day_end(day)
        while event_idx < len(events) and events[event_idx][0] <= day_end:
            current_value = events[event_idx][1]
            event_idx += 1
        points.append(
            {
                "t": _day_start(day).isoformat(),
                "portfolio_value": round(current_value, 2),
                "balance": round(current_value, 2),
                "cumulative_pl": round(current_value - baseline, 2),
            }
        )
        day += timedelta(days=1)

    return points
