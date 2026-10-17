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


def _lot_key(symbol: str, asset_class: str | None) -> tuple[str, str]:
    """Equity and option fills on the same ticker are different instruments."""
    return (symbol.upper(), asset_class or "us_equity")


def _priced_fill(order: Order) -> float | None:
    """Execution price, or None when the stored price is missing.

    A non-positive fill with no cost is an unavailable quote, not a free trade.
    """
    if order.status != "filled" or order.fill_price is None:
        return None
    try:
        price = float(order.fill_price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def replay_filled_orders(orders: list[Order]) -> dict[tuple[str, str], _Book]:
    books, _events = _replay_fills(orders)
    return books


def realized_pnl_events(orders: list[Order]) -> list[tuple[datetime, float]]:
    """Realized trade P&L after each priced fill. Unrealized is not invented here."""
    _books, events = _replay_fills(orders)
    return events


def _replay_fills(orders: list[Order]) -> tuple[dict[tuple[str, str], _Book], list[tuple[datetime, float]]]:
    books: dict[tuple[str, str], _Book] = {}
    events: list[tuple[datetime, float]] = []
    filled = [o for o in orders if _priced_fill(o) is not None]
    filled.sort(key=_order_ts)
    for order in filled:
        key = _lot_key(order.symbol, order.asset_class)
        book = books.setdefault(key, _Book(asset_class=order.asset_class))
        book.asset_class = key[1]
        _apply_fill(book, order, key[1])
        realized = round(sum(row.realized_pl for row in books.values()), 2)
        events.append((_order_ts(order), realized))
    return books, events


def _apply_fill(book: _Book, order: Order, asset_class: str) -> None:
    mult = position_multiplier(asset_class)
    px = float(order.fill_price)
    if order.side == "buy":
        if book.qty < 0:
            cover = min(order.qty, abs(book.qty))
            book.realized_pl += (book.avg_cost - px) * cover * mult
            book.qty += cover
            leftover = order.qty - cover
            if abs(book.qty) < 1e-9:
                book.qty = 0.0
                book.avg_cost = 0.0
            if leftover > 0:
                book.qty = leftover
                book.avg_cost = px
        elif book.qty > 0:
            book.avg_cost = (book.avg_cost * book.qty + px * order.qty) / (book.qty + order.qty)
            book.qty += order.qty
        else:
            book.avg_cost = px
            book.qty = order.qty
    elif book.qty > 0:
        close = min(order.qty, book.qty)
        book.realized_pl += (px - book.avg_cost) * close * mult
        book.qty -= close
        leftover = order.qty - close
        if abs(book.qty) < 1e-9:
            book.qty = 0.0
            book.avg_cost = 0.0
        if leftover > 0:
            book.qty = -leftover
            book.avg_cost = px
    elif book.qty < 0:
        book.avg_cost = (book.avg_cost * abs(book.qty) + px * order.qty) / (abs(book.qty) + order.qty)
        book.qty -= order.qty
    else:
        book.qty = -order.qty
        book.avg_cost = px


def _settlement_basis(order: Order) -> tuple[float, float] | None:
    """(average cost, signed qty closed) stored on a fill that reduced a lot."""
    raw = getattr(order, "settlement", None)
    if not isinstance(raw, dict):
        return None
    if str(order.status or "") != "filled" or order.fill_price is None:
        return None
    try:
        basis = float(raw.get("basis"))
        closed = float(raw.get("closed_qty"))
        fill = float(order.fill_price)
    except (TypeError, ValueError):
        return None
    if closed == 0 or basis < 0 or fill < 0:
        return None
    return basis, closed


def _settlement_realized(orders: list[Order], symbol: str, asset_class: str, mult: int) -> Decimal | None:
    """P&L of closes that recorded the lot's average cost. None when none did."""
    total = Decimal(0)
    found = False
    for order in orders:
        if _lot_key(order.symbol, order.asset_class) != (symbol, asset_class):
            continue
        parsed = _settlement_basis(order)
        if parsed is None:
            continue
        basis, closed = parsed
        total += (_dec(float(order.fill_price)) - _dec(basis)) * _dec(closed) * Decimal(mult)
        found = True
    if not found:
        return None
    return total


def account_trade_pnl(orders: list[Order], positions: list[Position]) -> float:
    """The Overall P&L total: realized plus unrealized, in cents, summed.

    This is the figure Portfolio labels Overall P&L. It is not portfolio value
    minus the starting balance.
    """
    total = sum((_dec(row.total_pl) for row in symbol_pnl_rows(orders, positions)), Decimal(0))
    return _money(total)


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
    pos_by_key = {_lot_key(p.symbol, p.asset_class): p for p in positions}
    keys = set(books) | set(pos_by_key)
    for order in orders:
        if _settlement_basis(order) is not None:
            keys.add(_lot_key(order.symbol, order.asset_class))
    rows: list[SymbolPnlRow] = []
    for sym, asset_class in sorted(keys):
        book = books.get((sym, asset_class), _Book())
        pos = pos_by_key.get((sym, asset_class))
        asset_class = pos.asset_class if pos else asset_class
        mult = position_multiplier(asset_class)
        pos_qty = float(pos.qty) if pos is not None else 0.0
        settled = _settlement_realized(orders, sym, asset_class, mult)
        # Replay can turn a close into a new short when the opening fill is not stored
        # on this contract. The close records the basis it actually used.
        if settled is not None and (
            abs(float(book.qty) - pos_qty) > 1e-6
            or (abs(pos_qty) < 1e-9 and abs(float(book.realized_pl)) < 1e-9 and settled != 0)
        ):
            realized = settled
            qty = pos_qty
        else:
            realized = _dec(book.realized_pl)
            qty = pos.qty if pos else book.qty
        unrealized = Decimal(0)
        if pos is not None and pos.qty != 0 and pos.current_price is not None and pos.avg_cost is not None:
            unrealized = (_dec(pos.current_price) - _dec(pos.avg_cost)) * _dec(pos.qty) * Decimal(mult)
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


def _lots_match(lots: dict[tuple[str, str], _Book], positions: list[Position]) -> bool:
    expected = {
        _lot_key(p.symbol, p.asset_class): float(p.qty)
        for p in positions
        if abs(float(p.qty or 0)) > 1e-6
    }
    actual = {key: lot.qty for key, lot in lots.items() if abs(lot.qty) > 1e-6}
    if set(expected) != set(actual):
        return False
    return all(abs(expected[key] - actual[key]) <= 0.01 for key in expected)


def _replay_equity_events(
    user: User,
    orders: list[Order],
    positions: list[Position],
    baseline: float,
) -> tuple[list[tuple[datetime, float]], str | None]:
    """Cash plus marked positions after each fill, then the live mark.

    At a fill, the traded symbol is marked at the fill price and other open
    lots stay at average cost. The live point uses each position's current price.
    """
    events: list[tuple[datetime, float]] = []
    cash = baseline
    open_lots: dict[tuple[str, str], _Book] = {}
    filled = [o for o in orders if _priced_fill(o) is not None]
    filled.sort(key=_order_ts)

    for order in filled:
        key = _lot_key(order.symbol, order.asset_class)
        px = float(order.fill_price)
        mult = position_multiplier(key[1])
        cost = round(order.qty * px * mult, 2)
        lot = open_lots.setdefault(key, _Book(asset_class=key[1]))
        lot.asset_class = key[1]

        if order.side == "buy":
            cash -= cost
            if lot.qty < 0:
                cover = min(order.qty, abs(lot.qty))
                lot.qty += cover
                leftover = order.qty - cover
                if abs(lot.qty) < 1e-9:
                    lot.qty = 0.0
                    lot.avg_cost = 0.0
                if leftover > 0:
                    lot.qty = leftover
                    lot.avg_cost = px
            elif lot.qty > 0:
                lot.avg_cost = (lot.avg_cost * lot.qty + px * order.qty) / (lot.qty + order.qty)
                lot.qty += order.qty
            else:
                lot.avg_cost = px
                lot.qty = order.qty
        elif lot.qty > 0:
            cash += cost
            close = min(order.qty, lot.qty)
            lot.qty -= close
            leftover = order.qty - close
            if abs(lot.qty) < 1e-9:
                lot.qty = 0.0
                lot.avg_cost = 0.0
            if leftover > 0:
                lot.qty = -leftover
                lot.avg_cost = px
        elif lot.qty < 0:
            cash += cost
            lot.avg_cost = (lot.avg_cost * abs(lot.qty) + px * order.qty) / (abs(lot.qty) + order.qty)
            lot.qty -= order.qty
        else:
            cash += cost
            lot.qty = -order.qty
            lot.avg_cost = px

        marked = 0.0
        for lot_key, l in open_lots.items():
            if abs(l.qty) < 1e-9:
                continue
            mark = px if lot_key == key else l.avg_cost
            marked += l.qty * mark * position_multiplier(l.asset_class)

        portfolio_value = round(cash + marked, 2)
        ts = _order_ts(order)
        events.append((ts, portfolio_value))

    live_cash = user.cash_balance
    live_holdings = 0.0
    for pos in positions:
        mult = position_multiplier(pos.asset_class)
        price = pos.current_price
        if price is None:
            continue
        live_holdings += pos.qty * price * mult
    live_value = round(live_cash + live_holdings, 2)
    lots_match = _lots_match(open_lots, positions)
    now = datetime.now(timezone.utc)
    # The latest point is the current account value at this timestamp.
    # Earlier fill points are left as they were. Nothing is inserted between them.
    last_ts = _as_utc(events[-1][0]) if events else None
    if not events or events[-1][1] != live_value or last_ts is None or last_ts < now:
        events.append((now, live_value))
    if lots_match:
        return events, None
    return events, (
        "The latest point is the current account value. Earlier points are the value after each priced fill. "
        "Saved orders do not match the open book, so those earlier points can differ."
    )


def portfolio_history(
    user: User, orders: list[Order], positions: list[Position]
) -> tuple[list[dict], str | None]:
    """Observed portfolio value, plus a note when fill history cannot be plotted."""
    baseline = account_baseline(user)
    account_start = _as_utc(user.created_at) if user.created_at else datetime.now(timezone.utc)
    events, history_note = _replay_equity_events(user, orders, positions, baseline)

    raw: list[tuple[datetime, float]] = [(account_start, round(baseline, 2))]
    raw.extend((_as_utc(ts), value) for ts, value in events)
    raw.sort(key=lambda item: item[0])

    points: list[dict] = []
    realized = realized_pnl_events(orders)
    for ts, value in raw:
        rounded = round(float(value), 2)
        trade_pl = 0.0
        for event_ts, event_pl in realized:
            if event_ts <= ts:
                trade_pl = event_pl
            else:
                break
        point = {
            "t": ts.isoformat(),
            "portfolio_value": rounded,
            "balance": rounded,
            "cumulative_pl": trade_pl,
        }
        if points and points[-1]["t"] == point["t"]:
            points[-1] = point
            continue
        points.append(point)
    if points:
        points[-1]["cumulative_pl"] = account_trade_pnl(orders, positions)
    return points, history_note


def pnl_history_points(user: User, orders: list[Order], positions: list[Position]) -> list[dict]:
    """Portfolio value and trade P&L on the same observations.

    portfolio_value is cash plus marked positions.
    cumulative_pl is trade P&L: realized at each fill, and the latest point is
    the Overall P&L total (realized + unrealized at the current mark).
    It is not portfolio value minus the starting balance.
    """
    points, _note = portfolio_history(user, orders, positions)
    return points
