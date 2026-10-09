from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.models.trading import Order, Position
from app.models.user import User
from app.services.fills import position_multiplier

_CENT = Decimal("0.01")


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
                book.qty += order.qty
            elif book.qty < 0:
                cover = min(order.qty, abs(book.qty))
                book.realized_pl += (book.avg_cost - px) * cover * mult
                book.qty += order.qty
                if book.qty > 0:
                    book.avg_cost = px
                elif book.qty == 0:
                    book.avg_cost = 0.0
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


def _money(amount: Decimal) -> float:
    """Half-up to the cent, then a float for the existing row payload."""
    return float(amount.quantize(_CENT, rounding=ROUND_HALF_UP))


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


def symbol_pnl_rows(orders: list[Order], positions: list[Position]) -> list[SymbolPnlRow]:
    """Per-symbol P&L.

    unrealized = (mark − average) × qty × multiplier
    total = realized + unrealized

    qty is signed. A short (qty < 0) gains when the mark falls.
    Order rows have no fee field; this function does not invent one.
    """
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
        unrealized = Decimal(0)
        if pos is not None and pos.qty != 0:
            unrealized = (_dec(pos.current_price) - _dec(pos.avg_cost)) * _dec(pos.qty) * Decimal(mult)
        realized = _dec(book.realized_pl)
        realized_q = realized.quantize(_CENT, rounding=ROUND_HALF_UP)
        unrealized_q = unrealized.quantize(_CENT, rounding=ROUND_HALF_UP)
        rows.append(
            SymbolPnlRow(
                symbol=sym,
                asset_class=asset_class,
                qty=qty,
                realized_pl=_money(realized_q),
                unrealized_pl=_money(unrealized_q),
                total_pl=_money(realized_q + unrealized_q),
                is_open=bool(pos is not None and pos.qty != 0),
            )
        )
    return rows


def _utc_date(dt: datetime) -> date:
    return _as_utc(dt).date()


def _replay_equity_events(
    user: User,
    orders: list[Order],
    positions: list[Position],
    baseline: float,
) -> list[tuple[datetime, float]]:
    """Cash plus marked positions after each fill, then the live mark.

    At a fill, the traded symbol is marked at the fill price and other open
    lots stay at average cost. The live point uses each position's current price.
    """
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
                lot.qty += order.qty
            elif lot.qty < 0:
                lot.qty += order.qty
                if lot.qty > 0:
                    lot.avg_cost = px
                elif lot.qty == 0:
                    lot.avg_cost = 0.0
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
    """Observed portfolio value only.

    portfolio_value = cash + marked positions at that observation.
    Observations are account open, each fill, and the live mark.
    Days with no observation are omitted.
    """
    baseline = account_baseline(user)
    account_start = _as_utc(user.created_at) if user.created_at else datetime.now(timezone.utc)
    events = _replay_equity_events(user, orders, positions, baseline)

    raw: list[tuple[datetime, float]] = [(account_start, round(baseline, 2))]
    raw.extend((_as_utc(ts), value) for ts, value in events)
    raw.sort(key=lambda item: item[0])

    points: list[dict] = []
    for ts, value in raw:
        rounded = round(float(value), 2)
        point = {
            "t": ts.isoformat(),
            "portfolio_value": rounded,
            "balance": rounded,
            "cumulative_pl": round(rounded - baseline, 2),
        }
        if points and points[-1]["t"] == point["t"]:
            points[-1] = point
            continue
        points.append(point)
    return points
