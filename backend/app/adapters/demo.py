from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone

from app.analysis import black_scholes as bs
from app.analysis.options_rules import build_quote_meta
from app.schemas.market import Expiration, OptionChain, OptionContract, Quote, QuoteMetaModel, SearchHit

UNIVERSE: dict[str, dict] = {
    "SPX": {
        "name": "S&P 500 INDEX",
        "asset_class": "us_index",
        "base": 5682.40,
        "market_cap": None,
        "pe_ttm": 24.8,
        "div_yield": 0.0128,
        "expense_ratio": None,
        "beta_5y": 1.0,
        "avg_volume": 2_150_000_000,
    },
    "AAPL": {
        "name": "Apple Inc.",
        "asset_class": "us_equity",
        "base": 227.15,
        "market_cap": 3.46e12,
        "pe_ttm": 34.2,
        "div_yield": 0.0044,
        "expense_ratio": None,
        "beta_5y": 1.18,
        "avg_volume": 54_200_000,
    },
    "NVDA": {
        "name": "NVIDIA Corporation",
        "asset_class": "us_equity",
        "base": 118.40,
        "market_cap": 2.91e12,
        "pe_ttm": 52.1,
        "div_yield": 0.0003,
        "expense_ratio": None,
        "beta_5y": 1.72,
        "avg_volume": 312_000_000,
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "asset_class": "us_equity",
        "base": 428.60,
        "market_cap": 3.19e12,
        "pe_ttm": 36.4,
        "div_yield": 0.0071,
        "expense_ratio": None,
        "beta_5y": 0.92,
        "avg_volume": 21_400_000,
    },
    "TSLA": {
        "name": "Tesla, Inc.",
        "asset_class": "us_equity",
        "base": 241.80,
        "market_cap": 7.75e11,
        "pe_ttm": 68.5,
        "div_yield": 0.0,
        "expense_ratio": None,
        "beta_5y": 2.04,
        "avg_volume": 88_000_000,
    },
    "AMZN": {
        "name": "Amazon.com, Inc.",
        "asset_class": "us_equity",
        "base": 196.20,
        "market_cap": 2.06e12,
        "pe_ttm": 41.3,
        "div_yield": 0.0,
        "expense_ratio": None,
        "beta_5y": 1.16,
        "avg_volume": 41_000_000,
    },
    "META": {
        "name": "Meta Platforms, Inc.",
        "asset_class": "us_equity",
        "base": 512.30,
        "market_cap": 1.30e12,
        "pe_ttm": 27.9,
        "div_yield": 0.0035,
        "expense_ratio": None,
        "beta_5y": 1.21,
        "avg_volume": 14_800_000,
    },
    "SPY": {
        "name": "SPDR S&P 500 ETF Trust",
        "asset_class": "us_etf",
        "base": 567.10,
        "market_cap": 5.6e11,
        "pe_ttm": 24.6,
        "div_yield": 0.0124,
        "expense_ratio": 0.000945,
        "beta_5y": 1.0,
        "avg_volume": 62_000_000,
    },
}


def _seed(symbol: str) -> float:
    digest = hashlib.sha256(symbol.encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _server_today() -> date:
    return _now().date()


def _price_at(symbol: str, when: datetime) -> float:
    meta = UNIVERSE.get(symbol.upper(), {"base": 100.0})
    base = float(meta["base"])
    s = _seed(symbol)
    t = when.timestamp() / 86400
    wave = math.sin(t * 0.35 + s * 6) * 0.012 + math.sin(t * 1.7 + s) * 0.006
    return round(base * (1 + wave), 2)


class DemoAdapter:
    name = "demo"
    feed = "indicative"

    async def search(self, query: str) -> list[SearchHit]:
        from app.services.symbol_catalog import search_instruments

        return search_instruments(query)

    async def quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        meta = UNIVERSE.get(symbol, {
            "name": symbol,
            "asset_class": "us_equity",
            "base": 100.0,
            "market_cap": 8e9,
            "pe_ttm": 18.0,
            "div_yield": 0.01,
            "expense_ratio": None,
            "beta_5y": 1.05,
            "avg_volume": 4_000_000,
        })
        now = _now()
        price = _price_at(symbol, now)
        prev = _price_at(symbol, now - timedelta(days=1))
        change = round(price - prev, 2)
        open_px = _price_at(symbol, now.replace(hour=13, minute=30, second=0, microsecond=0))
        high = round(max(price, open_px) * 1.006, 2)
        low = round(min(price, open_px) * 0.994, 2)
        expense = meta.get("expense_ratio")
        if meta.get("asset_class") in {"us_equity", "us_index"}:
            expense = None
        received = now
        quote_meta = QuoteMetaModel.model_validate(
            build_quote_meta(
                provider="demo",
                feed="other",
                quoted_at=received,
                received_at=received,
                bid=round(price * 0.999, 2),
                ask=round(price * 1.001, 2),
                bid_size=100,
                ask_size=100,
                now=received,
                feed_delayed=False,
            )
        )
        return Quote(
            symbol=symbol,
            name=meta["name"],
            price=price,
            change=change,
            change_pct=round((change / prev) * 100, 2) if prev else 0.0,
            open=open_px,
            high=high,
            low=low,
            volume=int(meta.get("avg_volume", 1_000_000) * 0.62),
            avg_volume=float(meta.get("avg_volume", 1_000_000)),
            week_52_high=round(price * 1.18, 2),
            week_52_low=round(price * 0.72, 2),
            market_cap=meta.get("market_cap"),
            pe_ttm=meta.get("pe_ttm"),
            div_yield=meta.get("div_yield"),
            expense_ratio=expense,
            beta_5y=meta.get("beta_5y"),
            source="demo",
            secondary_source=None,
            bid=quote_meta.bid,
            ask=quote_meta.ask,
            quote_meta=quote_meta,
            asset_class=str(meta.get("asset_class") or "us_equity"),
            as_of=received.isoformat(),
        )

    async def bars(self, symbol: str, timeframe: str, limit: int = 180) -> list[dict]:
        symbol = symbol.upper()
        step = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1H": timedelta(hours=1),
            "4H": timedelta(hours=4),
            "1D": timedelta(days=1),
            "1W": timedelta(weeks=1),
        }.get(timeframe, timedelta(days=1))
        now = _now()
        out = []
        for i in range(limit, 0, -1):
            t = now - step * i
            c = _price_at(symbol, t)
            o = _price_at(symbol, t - step / 3)
            h = max(o, c) * (1.003 + 0.002 * math.sin(i))
            l = min(o, c) * (0.997 - 0.002 * math.cos(i))
            v = 1_200_000 + int(abs(math.sin(i * 0.4 + _seed(symbol))) * 800_000)
            out.append({"t": t.isoformat(), "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2), "v": v})
        return out

    async def vendor_daily_bars(self, symbol: str, *, start: str, end: str) -> list[dict]:
        """Synthetic demo prices are not marks. Daily P&L stays unavailable."""
        _ = (symbol, start, end)
        return []

    async def expirations(self, symbol: str) -> list[Expiration]:
        today = _server_today()
        dates: list[date] = []
        # weekly Fridays for 12 weeks, then monthlies, then a LEAP (≥15 for offline/e2e desks)
        d = today
        while len(dates) < 12:
            d += timedelta(days=1)
            if d.weekday() == 4:
                dates.append(d)
        month = today.replace(day=1)
        for _ in range(1, 6):
            month = (month.replace(day=28) + timedelta(days=8)).replace(day=1)
            # third Friday approximation
            first = month
            friday = first + timedelta(days=(4 - first.weekday()) % 7)
            third = friday + timedelta(days=14)
            if third > today and third not in dates:
                dates.append(third)
        leap = today + timedelta(days=365)
        while leap.weekday() != 4:
            leap += timedelta(days=1)
        dates.append(leap)
        dates = sorted({x for x in dates if x >= today})
        out = []
        for exp in dates:
            dte = (exp - today).days
            kind = "weekly" if dte <= 21 else "monthly" if dte <= 120 else "leaps"
            out.append(
                Expiration(
                    date=exp.isoformat(),
                    dte=dte,
                    kind=kind,
                    near_expiry=dte <= 2,
                    earnings_highlight=False,
                )
            )
        return out

    async def option_chain(self, symbol: str, expiry: str) -> OptionChain:
        """Deterministic synthetic chain. Always labelled ``simulated`` — never live data."""
        q = await self.quote(symbol)
        spot = q.price
        try:
            raw_dte = (date.fromisoformat(expiry) - _server_today()).days
        except (TypeError, ValueError):
            return OptionChain(
                symbol=symbol.upper(),
                expiry=expiry,
                spot=spot,
                feed="indicative",
                contracts=[],
                status="unavailable",
                source="internal simulator",
                expiry_valid=False,
                notes=[f"Expiry {expiry!r} is not an ISO date, so no chain can be generated."],
            )
        dte = max(raw_dte, 1)
        years = bs.year_fraction(dte)
        # Strikes sit on a listed increment, and the increment is sized to the expected move so a
        # weekly ladder is not padded with worthless $40-wide wings the way a fixed step would be.
        base_iv = 0.30 if symbol.upper() == "TSLA" else 0.22
        sigma_move = spot * base_iv * math.sqrt(years)
        step = min((s for s in (0.5, 1.0, 2.5, 5.0, 10.0, 20.0)), key=lambda s: abs(s - sigma_move / 2.0))
        atm = round(spot / step) * step
        strikes = [round(atm + step * i, 2) for i in range(-8, 9) if atm + step * i > 0]
        contracts: list[OptionContract] = []
        for strike in strikes:
            # Log-moneyness drives a skewed smile: downside puts bid up, upside calls cheaper.
            k = math.log(strike / spot)
            iv = min(max(base_iv + 1.4 * k * k - 0.35 * k, 0.08), 2.5)
            # Liquidity is a bell around the money measured in expected moves, so the wings fail
            # the documented gates — which is what a real chain looks like and what §5.6 catches.
            nearness = math.exp(-((strike - spot) ** 2) / (2 * (1.8 * sigma_move) ** 2))
            for side in ("call", "put"):
                # Downside puts carry more resting interest than upside calls, as hedging demand
                # does on a real chain, so the put/call ratios the analysis reads are not a
                # degenerate 1.000 on every expiry.
                hedge = 1.0 + (0.35 if (side == "put") == (strike < spot) else 0.0)
                open_interest = int((60 + 9000 * nearness) * hedge)
                volume = int(open_interest * (0.12 + 0.5 * nearness))
                g = bs.greeks(spot=spot, strike=strike, years=years, vol=iv, side=side)  # type: ignore[arg-type]
                if g is None:
                    continue
                mid = max(round(g.price, 2), 0.01)
                # Spreads widen on the illiquid wings, and a penny option can only be quoted a
                # tick wide — which is a huge percentage of mid, so those strikes breach the
                # §5.5 cap exactly as they do on a live chain.
                half = max(round(mid * (0.015 + 0.085 * (1.0 - nearness)), 2), 0.01)
                bid = max(round(mid - half, 2), 0.0)
                ask = round(mid + half, 2)
                prev = max(round(mid / (1.0 + 0.04 * (1 if side == "call" else -1)), 2), 0.01)
                contracts.append(
                    OptionContract(
                        symbol=f"{symbol}{expiry.replace('-', '')[2:]}{side[0].upper()}{int(strike * 1000):08d}",
                        strike=strike,
                        side=side,  # type: ignore[arg-type]
                        bid=bid,
                        ask=ask,
                        bid_size=int(5 + 60 * nearness),
                        ask_size=int(5 + 60 * nearness),
                        last=mid,
                        prev_close=prev,
                        change=round(mid - prev, 2),
                        change_pct=round((mid - prev) / prev, 4),
                        volume=volume,
                        open_interest=open_interest,
                        iv=round(iv, 4),
                        delta=round(g.delta, 4),
                        gamma=round(g.gamma, 4),
                        theta=round(g.theta, 4),
                        vega=round(g.vega, 4),
                        rho=round(g.rho, 4),
                        greeks_source="model",
                        iv_source="model",
                        multiplier=100,
                        quote_as_of=_now().isoformat(),
                        quote_meta=QuoteMetaModel.model_validate(
                            build_quote_meta(
                                provider="demo",
                                feed="other",
                                quoted_at=_now(),
                                received_at=_now(),
                                bid=bid,
                                ask=ask,
                                bid_size=int(5 + 60 * nearness),
                                ask_size=int(5 + 60 * nearness),
                                feed_delayed=False,
                            )
                        ),
                    )
                )
        return OptionChain(
            symbol=symbol.upper(),
            expiry=expiry,
            spot=spot,
            feed="indicative",
            contracts=contracts,
            status="simulated",
            source="internal simulator",
            spot_source="demo",
            greeks_source="model",
            as_of=_now().isoformat(),
            dte=raw_dte,
            expiry_valid=raw_dte >= 0,
            notes=[
                "Synthetic chain from the internal simulator. Quotes are Black-Scholes values on a generated "
                "volatility smile and the Greeks are the same model's derivatives, so the ladder is internally "
                "consistent — but open interest, volume and spreads are generated, not market data. Do not trade "
                "from these numbers."
            ],
        )

    async def submit_order(self, **kwargs) -> dict:
        result = {"status": "filled", "broker": "demo_paper", **kwargs}
        if kwargs.get("order_class") == "mleg" and kwargs.get("limit_price") is not None:
            result["filled_avg_price"] = abs(float(kwargs["limit_price"]))
        return result
