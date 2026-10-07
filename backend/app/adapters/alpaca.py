from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

from app.adapters.demo import DemoAdapter
from app.analysis import black_scholes as bs
from app.config import Settings
from app.analysis.options_rules import build_quote_meta
from app.schemas.market import Expiration, OptionChain, OptionContract, Quote, QuoteMetaModel, SearchHit

#: Cash-settled indices have no listed chain on Alpaca (US equities and ETFs only).
CASH_INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX", "XSP", "DJX", "XEO", "OEX"}


def _is_cash_index(symbol: str) -> bool:
    return symbol.upper() in CASH_INDEX_SYMBOLS


def _is_live_expiry(expiry: str, today: date) -> bool:
    try:
        return date.fromisoformat(expiry) >= today
    except (TypeError, ValueError):
        return False


def _dte(expiry: str, today: date) -> int | None:
    try:
        return (date.fromisoformat(expiry) - today).days
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    """Parse a vendor number. Absent stays absent — it never becomes 0.0."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    f = _opt_float(value)
    return None if f is None else int(f)


def _side_from_occ(occ: str, declared: Any) -> str | None:
    if isinstance(declared, str) and declared.lower() in {"call", "put"}:
        return declared.lower()
    # OCC symbol: ROOT + YYMMDD + C|P + 8-digit strike
    if len(occ) >= 9:
        marker = occ[-9]
        if marker == "C":
            return "call"
        if marker == "P":
            return "put"
    return None


def _strike_from_occ(occ: str) -> float | None:
    if len(occ) >= 8 and occ[-8:].isdigit():
        return int(occ[-8:]) / 1000.0
    return None


def _json_or_none(res: Any) -> Any:
    try:
        return res.json()
    except Exception:  # noqa: BLE001
        return None


def alpaca_order_error_message(body: Any, *, fallback: str) -> str:
    """The broker's own sentence, when the response has one."""
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def _whole_order_qty(qty: Any) -> Any:
    """Alpaca rejects a fractional-looking option qty such as 1.0."""
    try:
        number = float(qty)
    except (TypeError, ValueError):
        return qty
    if number > 0 and number == int(number):
        return int(number)
    return qty


def _parse_snapshot(occ: str, snap: Any, meta: Any = None) -> OptionContract | None:
    """Merge one Alpaca option snapshot with its contract reference row.

    The snapshot feed carries quotes, trades, IV and Greeks; strike, call/put, open interest
    and the prior close come from ``/v2/options/contracts``. Returns ``None`` when the
    contract cannot even be identified.
    """
    if not isinstance(snap, dict):
        return None
    greeks = snap.get("greeks") or {}
    quote_row = snap.get("latestQuote") or {}
    trade = snap.get("latestTrade") or {}
    daily = snap.get("dailyBar") or {}
    prev = snap.get("prevDailyBar") or {}
    details = meta if isinstance(meta, dict) else (snap.get("details") or {})

    side = _side_from_occ(occ, details.get("type"))
    strike = _opt_float(details.get("strike_price")) or _strike_from_occ(occ)
    if side is None or strike is None or strike <= 0:
        return None

    last = _opt_float(trade.get("p")) or _opt_float(daily.get("c"))
    prev_close = _opt_float(prev.get("c")) or _opt_float(details.get("close_price"))
    change = last - prev_close if last is not None and prev_close is not None else None
    change_pct = change / prev_close if change is not None and prev_close else None
    delta = _opt_float(greeks.get("delta"))
    has_greeks = any(_opt_float(greeks.get(k)) is not None for k in ("delta", "gamma", "theta", "vega"))
    iv = _opt_float(snap.get("impliedVolatility"))

    return OptionContract(
        symbol=occ,
        strike=strike,
        side=side,  # type: ignore[arg-type]
        bid=_opt_float(quote_row.get("bp")),
        ask=_opt_float(quote_row.get("ap")),
        bid_size=_opt_int(quote_row.get("bs")),
        ask_size=_opt_int(quote_row.get("as")),
        last=last,
        prev_close=prev_close,
        change=change,
        change_pct=change_pct,
        volume=_opt_int(daily.get("v")),
        open_interest=_opt_int(details.get("open_interest")),
        iv=iv,
        delta=delta,
        gamma=_opt_float(greeks.get("gamma")),
        theta=_opt_float(greeks.get("theta")),
        vega=_opt_float(greeks.get("vega")),
        rho=_opt_float(greeks.get("rho")),
        greeks_source="vendor" if has_greeks else "unavailable",
        iv_source="vendor" if iv is not None else "unavailable",
        quote_as_of=quote_row.get("t") or trade.get("t"),
        multiplier=_opt_int(details.get("multiplier")),
    )


def _fill_model_greeks(contracts: list[OptionContract], spot: float | None, dte: int | None) -> None:
    """Compute Black-Scholes Greeks in place for contracts the vendor did not cover.

    Anything filled here is tagged ``greeks_source="model"`` so the UI labels it MODEL.
    Vendor-published Greeks are never overwritten.
    """
    if spot is None or spot <= 0 or dte is None:
        return
    years = bs.year_fraction(dte)
    for c in contracts:
        if c.greeks_source == "vendor":
            continue
        vol = c.iv
        if vol is None:
            mid = None
            if c.bid is not None and c.ask is not None and (c.bid > 0 or c.ask > 0):
                mid = (c.bid + c.ask) / 2.0
            elif c.last:
                mid = c.last
            if mid is None or mid <= 0:
                continue
            vol = bs.implied_vol(price=mid, spot=spot, strike=c.strike, years=years, side=c.side)
            if vol is None:
                continue
            c.iv = round(vol, 6)
            c.iv_source = "model"
        g = bs.greeks(spot=spot, strike=c.strike, years=years, vol=vol, side=c.side)
        if g is None:
            continue
        c.delta = round(g.delta, 6)
        c.gamma = round(g.gamma, 6)
        c.theta = round(g.theta, 6)
        c.vega = round(g.vega, 6)
        c.rho = round(g.rho, 6)
        c.greeks_source = "model"


class AlpacaAdapter:
    name = "alpaca"
    feed = "indicative"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.demo = DemoAdapter()
        self.feed = "opra" if settings.alpaca_trading_mode == "live" else "indicative"

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key_id,
            "APCA-API-SECRET-KEY": self.settings.alpaca_api_secret_key,
        }

    async def _get(self, base: str, path: str, params: dict | None = None) -> Any | None:
        if not self.settings.alpaca_keys_present:
            return None
        url = f"{base}{path}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=self._headers(), params=params)
                if res.status_code >= 400:
                    logger.warning("Alpaca {} {} -> {}", path, res.status_code, res.text[:200])
                    return None
                return res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca request failed {}: {}", path, exc)
            return None

    async def search(self, query: str) -> list[SearchHit]:
        from app.services.symbol_catalog import Instrument, search_instruments

        extras: list[Instrument] = []
        # Empty focus shows the backlog only. A typed query may also include
        # broker assets, which pass through the same type filter.
        if query.strip():
            data = await self._get(
                self.settings.resolved_broker_base_url,
                "/v2/assets",
                {"status": "active", "asset_class": "us_equity"},
            )
            if isinstance(data, list):
                for row in data:
                    if not isinstance(row, dict):
                        continue
                    extras.append(
                        Instrument(
                            symbol=str(row.get("symbol") or ""),
                            name=str(row.get("name") or ""),
                            asset_class=str(row.get("class") or row.get("asset_class") or ""),
                        )
                    )
        return search_instruments(query, extras)

    async def quote(self, symbol: str) -> Quote:
        from app.services.live_quotes import get_live_quote

        live = await get_live_quote(symbol, self.settings)
        if live.price is not None:
            return live
        # Paper orders / scan still need a number when every live feed is dark.
        # The dashboard ticker panel does NOT use this path — it hits /market/quote.
        fallback = await self.demo.quote(symbol)
        fallback.status = "unavailable"
        fallback.source = "unavailable"
        fallback.secondary_source = "internal demo (live quote unavailable)"
        return fallback

    async def bars(self, symbol: str, timeframe: str, limit: int = 400) -> list[dict]:
        tf_map = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1H": "1Hour", "4H": "4Hour", "1D": "1Day", "1W": "1Week"}
        # Alpaca returns only the most recent bar(s) unless ``start`` is set.
        lookback_days = {
            "1m": max(3, limit // (6 * 60) + 2),
            "5m": max(5, limit // (6 * 12) + 2),
            "15m": max(10, limit // (6 * 4) + 3),
            "30m": max(14, limit // (6 * 2) + 3),
            "1H": max(30, limit // 6 + 5),
            "4H": max(90, limit // 2 + 10),
            "1D": max(400, limit + 30),
            "1W": max(400 * 7, limit * 7 + 60),
        }
        symbol = symbol.upper()
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days.get(timeframe, 400))).strftime("%Y-%m-%d")
        params = {
            "timeframe": tf_map.get(timeframe, "1Day"),
            "limit": min(limit, 10000),
            "adjustment": "raw",
            "start": start,
        }
        data = await self._get(
            self.settings.resolved_data_base_url,
            f"/v2/stocks/{symbol}/bars",
            params,
        )
        raw = (data or {}).get("bars") if isinstance(data, dict) else None
        if not raw:
            multi = dict(params)
            multi["symbols"] = symbol
            data = await self._get(
                self.settings.resolved_data_base_url,
                "/v2/stocks/bars",
                multi,
            )
            packed = (data or {}).get("bars") if isinstance(data, dict) else None
            if isinstance(packed, dict):
                raw = packed.get(symbol) or packed.get(symbol.upper())
            else:
                raw = packed
        if raw and len(raw) >= 8:
            return [
                {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
                for b in raw
            ][-limit:]
        from app.services.live_quotes import yahoo_ohlc_bars

        ybars = await yahoo_ohlc_bars(symbol, timeframe, limit)
        if ybars:
            return ybars
        return await self.demo.bars(symbol, timeframe, limit)

    async def vendor_daily_bars(self, symbol: str, *, start: str, end: str) -> list[dict]:
        """Daily closes from Alpaca or Yahoo. Empty when the feed has no prices.

        The chart path may fall back to the demo generator. Daily P&L must not.
        """
        from app.services.occ_symbol import parse_occ

        symbol = symbol.upper()
        if parse_occ(symbol):
            return await self.option_bars(symbol, start=start, end=end, timeframe="1Day", limit=1000)
        params = {
            "timeframe": "1Day",
            "limit": 10000,
            "adjustment": "raw",
            "start": start,
            "end": end,
        }
        data = await self._get(
            self.settings.resolved_data_base_url,
            f"/v2/stocks/{symbol}/bars",
            params,
        )
        raw = (data or {}).get("bars") if isinstance(data, dict) else None
        if not raw:
            multi = dict(params)
            multi["symbols"] = symbol
            data = await self._get(
                self.settings.resolved_data_base_url,
                "/v2/stocks/bars",
                multi,
            )
            packed = (data or {}).get("bars") if isinstance(data, dict) else None
            if isinstance(packed, dict):
                raw = packed.get(symbol) or packed.get(symbol.upper())
            else:
                raw = packed
        if raw:
            mapped = [
                {"t": b.get("t"), "c": b.get("c")}
                for b in raw
                if isinstance(b, dict) and b.get("c") is not None
            ]
            if mapped:
                return mapped
        from app.services.live_quotes import yahoo_ohlc_bars

        return await yahoo_ohlc_bars(symbol, "1D", 1000)

    async def _option_contracts(
        self,
        symbol: str,
        expiry: str | None = None,
        pages: int | None = None,
        *,
        side: str | None = None,
        expiration_gte: str | None = None,
    ) -> list[dict]:
        """Paginated ``/v2/options/contracts`` until the vendor is exhausted.

        The reference data (strike, call/put, open interest, prior close) is only published
        here — the snapshot feed carries quotes and Greeks but no contract metadata.

        Alpaca silently truncates to a handful of near-dated contracts when neither
        ``expiration_date`` nor ``expiration_date_gte`` is set (no ``next_page_token`` either).
        Callers that need the full calendar MUST pass ``expiration_gte`` (or a specific expiry).
        Max page size is 1000. There is no artificial "nearest N" date cap — pagination runs
        until ``next_page_token`` is absent (safety ceiling: ``pages`` or 200).
        """
        rows: list[dict] = []
        token: str | None = None
        max_pages = pages if pages is not None else 200
        for _ in range(max_pages):
            params: dict[str, Any] = {"underlying_symbols": symbol, "status": "active", "limit": 1000}
            if expiry:
                params["expiration_date"] = expiry
            elif expiration_gte:
                params["expiration_date_gte"] = expiration_gte
            if side in {"call", "put"}:
                params["type"] = side
            if token:
                params["page_token"] = token
            data = await self._get(self.settings.resolved_broker_base_url, "/v2/options/contracts", params)
            if not isinstance(data, dict):
                break
            page = data.get("option_contracts") or []
            rows.extend(r for r in page if isinstance(r, dict))
            token = data.get("next_page_token")
            if not token:
                break
        return rows

    async def expirations(self, symbol: str) -> list[Expiration]:
        """Every live, non-expired listed expiration for the underlying.

        Discovers dates by paginating call contracts with ``expiration_date_gte=today``
        until Alpaca returns no ``next_page_token``. Calls-only halves payload size;
        every listed expiry still appears on the call side. Past dates vs server UTC
        today are filtered out. No nearest-N / first-page-only truncation.
        """
        today = datetime.now(timezone.utc).date()
        symbol = symbol.upper()
        if _is_cash_index(symbol):
            # No listed equity-options chain on Alpaca — do not invent a single fake date.
            return []
        if not self.settings.alpaca_keys_present:
            # Offline / unkeyed desk only — never invent dates when live keys are configured.
            return await self.demo.expirations(symbol)
        rows = await self._option_contracts(
            symbol,
            side="call",
            expiration_gte=today.isoformat(),
        )
        if not rows:
            return []
        seen: set[str] = set()
        out: list[Expiration] = []
        for row in rows:
            exp = row.get("expiration_date")
            if not exp or exp in seen:
                continue
            try:
                exp_d = date.fromisoformat(exp)
            except (TypeError, ValueError):
                continue
            if exp_d < today:
                continue
            seen.add(exp)
            dte = (exp_d - today).days
            kind = "weekly" if dte <= 21 else "monthly" if dte <= 120 else "leaps"
            out.append(Expiration(date=exp, dte=dte, kind=kind, near_expiry=dte <= 2))
        out.sort(key=lambda e: e.date)
        return out

    async def option_chain(self, symbol: str, expiry: str) -> OptionChain:
        """Live OPRA/indicative option snapshots for one expiry.

        Degrades explicitly rather than silently: the returned chain always carries a
        ``status`` describing why it is not live, and Greeks the vendor did not publish are
        either computed locally and tagged ``model`` or left ``None``.
        """
        symbol = symbol.upper()
        today = datetime.now(timezone.utc).date()
        expiry_valid = _is_live_expiry(expiry, today)
        dte = _dte(expiry, today)

        if not expiry_valid:
            return await self._degraded_chain(
                symbol,
                expiry,
                "unavailable",
                [
                    f"Expiry {expiry!r} is not a valid, non-expired expiration as of server date {today.isoformat()}. "
                    "Pick a live expiry from the dashboard expiry picker."
                ],
                dte=dte,
                expiry_valid=False,
            )

        # Checked before credentials: an index has no chain here regardless of entitlement,
        # and that is the more useful thing to tell the trader. Do NOT fall back to the
        # simulator — inventing an SPX ladder would pretend a listed chain exists.
        if _is_cash_index(symbol):
            return await self._degraded_chain(
                symbol,
                expiry,
                "unsupported_underlying",
                [
                    f"{symbol} is a cash-settled index. Alpaca publishes options data for US equities and ETFs only, so "
                    f"there is no {symbol} chain on this vendor. Scan the tracking ETF (for example SPY for SPX) to get "
                    "a live entitled chain."
                ],
                dte=dte,
                allow_simulator=False,
            )

        if not self.settings.alpaca_keys_present:
            return await self._degraded_chain(
                symbol,
                expiry,
                "no_keys",
                [
                    "Add ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to .env and restart the backend. "
                    "No vendor options chain can be requested without credentials — APEX will not invent a demo ladder "
                    "unless ALLOW_OPTIONS_SIMULATOR=true is set explicitly for offline demos."
                ],
                dte=dte,
                # allow_simulator stays True so ALLOW_OPTIONS_SIMULATOR can opt-in; default flag is False.
            )

        snaps, status_code = await self._option_snapshots(symbol, expiry)
        if status_code in {401, 403}:
            return await self._degraded_chain(
                symbol,
                expiry,
                "no_entitlement",
                [
                    f"Alpaca returned HTTP {status_code} for the options snapshot feed. The credentials are present but "
                    f"this account is not entitled to the {self.feed} options feed."
                ],
                dte=dte,
                allow_simulator=False,
            )
        if not snaps:
            return await self._degraded_chain(
                symbol,
                expiry,
                "empty" if status_code == 200 else "unavailable",
                [
                    f"Alpaca returned no option snapshots for {symbol} {expiry}"
                    + (f" (HTTP {status_code})." if status_code not in {0, 200} else ".")
                ],
                dte=dte,
                allow_simulator=False,
            )

        quote = await self.quote(symbol)
        spot = quote.price
        spot_source = quote.source if spot is not None else None
        # Contract metadata for THIS expiry only — full pagination, no other dates mixed in.
        meta = {row.get("symbol"): row for row in await self._option_contracts(symbol, expiry) if row.get("symbol")}
        contracts: list[OptionContract] = []
        received = datetime.now(timezone.utc)
        from app.services.live_quotes import regular_market_sessions

        sessions = await regular_market_sessions(self.settings)
        for occ, snap in snaps.items():
            contract = _parse_snapshot(occ, snap, meta.get(occ))
            if contract is not None:
                contract.quote_meta = QuoteMetaModel.model_validate(
                    build_quote_meta(
                        provider="Alpaca",
                        feed=self.feed,
                        quoted_at=contract.quote_as_of,
                        received_at=received,
                        bid=contract.bid,
                        ask=contract.ask,
                        bid_size=contract.bid_size,
                        ask_size=contract.ask_size,
                        now=received,
                        sessions=sessions,
                    )
                )
                contracts.append(contract)
        contracts.sort(key=lambda c: (c.strike, c.side))
        if not contracts:
            return await self._degraded_chain(
                symbol,
                expiry,
                "empty",
                [f"Alpaca returned {len(snaps)} snapshots for {symbol} {expiry} but none carried a usable strike."],
                dte=dte,
                allow_simulator=False,
            )

        _fill_model_greeks(contracts, spot, dte)
        vendor = sum(1 for c in contracts if c.greeks_source == "vendor")
        model = sum(1 for c in contracts if c.greeks_source == "model")
        greeks_source = "vendor" if vendor and not model else "model" if model and not vendor else "vendor" if vendor else "unavailable"
        notes: list[str] = []
        if spot is None:
            notes.append(
                "No underlying reference price is available, so moneyness, ATM location and model Greeks cannot be computed."
            )
        return OptionChain(
            symbol=symbol,
            expiry=expiry,
            spot=spot,
            feed=self.feed,  # type: ignore[arg-type]
            contracts=contracts,
            status="live" if not model else "vendor_quotes_model_greeks",
            source=f"alpaca options snapshots ({self.feed})",
            spot_source=spot_source,
            greeks_source=greeks_source,  # type: ignore[arg-type]
            as_of=datetime.now(timezone.utc).isoformat(),
            dte=dte,
            expiry_valid=True,
            notes=notes,
        )

    async def _option_snapshots(self, symbol: str, expiry: str) -> tuple[dict[str, Any], int]:
        """Paginated option snapshots for one ``expiration_date`` only.

        Returns ``(snapshots_by_occ, last_http_status)``. Exhausts ``next_page_token``
        so a busy underlying is not truncated to the first 1000 contracts.
        """
        snaps: dict[str, Any] = {}
        token: str | None = None
        last_status = 0
        for _ in range(200):
            params: dict[str, Any] = {
                "expiration_date": expiry,
                "limit": 1000,
                "feed": self.feed,
            }
            if token:
                params["page_token"] = token
            status_code, data = await self._get_with_status(
                self.settings.resolved_data_base_url,
                "/v1beta1/options/snapshots/" + symbol,
                params,
            )
            last_status = status_code
            if status_code in {401, 403}:
                return {}, status_code
            if not isinstance(data, dict):
                break
            page = data.get("snapshots")
            if isinstance(page, dict):
                snaps.update(page)
            token = data.get("next_page_token")
            if not token:
                break
        return snaps, last_status

    async def _get_with_status(self, base: str, path: str, params: dict | None = None) -> tuple[int, Any | None]:
        """Like :meth:`_get` but surfaces the HTTP status so entitlement can be distinguished."""
        if not self.settings.alpaca_keys_present:
            return 0, None
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(f"{base}{path}", headers=self._headers(), params=params)
                if res.status_code >= 400:
                    logger.warning("Alpaca {} {} -> {}", path, res.status_code, res.text[:200])
                    return res.status_code, None
                return res.status_code, res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca request failed {}: {}", path, exc)
            return 0, None

    async def _degraded_chain(
        self,
        symbol: str,
        expiry: str,
        status: str,
        notes: list[str],
        *,
        dte: int | None,
        expiry_valid: bool = True,
        allow_simulator: bool = True,
    ) -> OptionChain:
        """Degraded chain payload for the combined options + Greeks screen.

        The internal Black-Scholes ladder is hard-gated behind
        ``ALLOW_OPTIONS_SIMULATOR=true`` (defaults false). Without that flag — even when
        ``allow_simulator`` is True for a missing-keys / empty-vendor equity path —
        contracts stay empty and ``status`` is preserved so the UI asks for Alpaca keys
        instead of inventing a fake chain.

        Cash-settled indices always pass ``allow_simulator=False``.
        """
        use_sim = bool(allow_simulator and self.settings.allow_options_simulator)
        if use_sim:
            try:
                chain = await self.demo.option_chain(symbol, expiry)
            except Exception:  # noqa: BLE001 — an unparsable expiry must not 500 the scan
                chain = OptionChain(symbol=symbol, expiry=expiry, spot=None, feed=self.feed, contracts=[])  # type: ignore[arg-type]
        else:
            # Honest empty degraded state — never attach the internal demo spot (e.g. 225.xx).
            from app.services.live_quotes import get_live_quote

            live = await get_live_quote(symbol, self.settings)
            spot = live.price if live.price is not None and live.status != "unavailable" else None
            chain = OptionChain(
                symbol=symbol,
                expiry=expiry,
                spot=spot,
                feed=self.feed,  # type: ignore[arg-type]
                contracts=[],
                spot_source=live.source if spot is not None else None,
            )
        chain.feed = self.feed  # type: ignore[assignment]
        chain.status = "simulated" if (use_sim and chain.contracts) else status  # type: ignore[assignment]
        chain.source = (
            f"internal simulator ({status})" if (use_sim and chain.contracts) else f"alpaca ({status})"
        )
        chain.greeks_source = "model" if chain.contracts else "unavailable"
        chain.as_of = datetime.now(timezone.utc).isoformat()
        chain.dte = dte
        chain.expiry_valid = expiry_valid
        extra = [f"Underlying degradation reason: {status}."]
        if status == "no_keys" and not use_sim:
            extra.append(
                "Configure ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in the project .env, then restart the API."
            )
        chain.notes = notes + extra
        return chain

    async def option_bars(
        self,
        contract_symbol: str,
        *,
        start: str,
        end: str,
        timeframe: str = "1Day",
        limit: int = 400,
    ) -> list[dict]:
        """Daily (or intraday) OHLC bars for one OCC option symbol."""
        if not self.settings.alpaca_keys_present or not contract_symbol:
            return []
        payload = await self._get(
            self.settings.resolved_data_base_url,
            "/v1beta1/options/bars",
            {
                "symbols": contract_symbol,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "limit": limit,
                "sort": "asc",
            },
        )
        if not payload:
            return []
        rows = (payload.get("bars") or {}).get(contract_symbol) or []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "t": row.get("t"),
                    "o": _opt_float(row.get("o")),
                    "h": _opt_float(row.get("h")),
                    "l": _opt_float(row.get("l")),
                    "c": _opt_float(row.get("c")),
                    "v": _opt_float(row.get("v")),
                }
            )
        return out

    async def _submit_combo(self, kwargs: dict, *, strict: bool) -> dict:
        """One multi-leg limit. A rejection is returned as-is and is not split into single-leg orders."""
        _ = strict
        if not self.settings.alpaca_keys_present:
            return await self.demo.submit_order(**kwargs)
        legs = kwargs.get("legs") or []
        payload = {
            "order_class": "mleg",
            "qty": str(_whole_order_qty(kwargs["qty"])),
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(kwargs.get("limit_price")),
            "legs": [
                {
                    "symbol": leg["symbol"],
                    "ratio_qty": str(int(leg.get("ratio_qty") or 1)),
                    "side": leg["side"],
                    "position_intent": leg.get("position_intent") or (
                        "buy_to_open" if leg.get("side") == "buy" else "sell_to_open"
                    ),
                }
                for leg in legs
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(
                    f"{self.settings.resolved_broker_base_url}/v2/orders",
                    headers=self._headers(),
                    json=payload,
                )
                if res.status_code >= 400:
                    reason = alpaca_order_error_message(
                        _json_or_none(res),
                        fallback=(res.text or "").strip()[:300] or f"Broker rejected the order ({res.status_code})",
                    )
                    logger.warning("Alpaca combo order failed {}", reason)
                    return {"status": "rejected", "rejected": True, "reason": reason}
                return res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca combo order error {}", exc)
            reason = str(exc).strip() or "Broker order failed"
            return {"status": "rejected", "rejected": True, "reason": reason}

    async def submit_order(self, **kwargs) -> dict:
        strict = bool(kwargs.pop("strict", False))
        if kwargs.get("order_class") == "mleg":
            return await self._submit_combo(kwargs, strict=strict)
        if not self.settings.alpaca_keys_present:
            return await self.demo.submit_order(**kwargs)
        payload = {
            "symbol": kwargs["symbol"],
            "qty": _whole_order_qty(kwargs["qty"]),
            "side": kwargs["side"],
            "type": kwargs.get("order_type", "market"),
            "time_in_force": "day",
        }
        if payload["type"] == "limit" and kwargs.get("limit_price") is not None:
            payload["limit_price"] = kwargs["limit_price"]
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(
                    f"{self.settings.resolved_broker_base_url}/v2/orders",
                    headers=self._headers(),
                    json=payload,
                )
                if res.status_code >= 400:
                    reason = alpaca_order_error_message(
                        _json_or_none(res),
                        fallback=(res.text or "").strip()[:300] or f"Broker rejected the order ({res.status_code})",
                    )
                    logger.warning("Alpaca order failed {}", reason)
                    if strict:
                        return {"status": "rejected", "rejected": True, "reason": reason}
                    return await self.demo.submit_order(**kwargs)
                return res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca order error {}", exc)
            reason = str(exc).strip() or "Broker order failed"
            if strict:
                return {"status": "rejected", "rejected": True, "reason": reason}
            return await self.demo.submit_order(**kwargs)
