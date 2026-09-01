from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DataFeed = Literal["indicative", "opra"]
QuoteStatus = Literal["live", "partial", "unavailable"]

#: Where a Greek / IV number came from. ``model`` means locally computed Black-Scholes.
ValueSource = Literal["vendor", "model", "unavailable"]

#: ``live`` vendor chain, ``vendor_quotes_model_greeks`` vendor prices with local Greeks,
#: ``simulated`` internal demo generator (never presented as live),
#: ``no_entitlement`` keys work but the options feed is not entitled,
#: ``no_keys`` no credentials in the environment,
#: ``unsupported_underlying`` e.g. a cash index with no listed chain on this vendor,
#: ``empty`` vendor answered with zero contracts for that expiry.
ChainStatus = Literal[
    "live",
    "vendor_quotes_model_greeks",
    "simulated",
    "no_entitlement",
    "no_keys",
    "unsupported_underlying",
    "empty",
    "unavailable",
]


class Quote(BaseModel):
    symbol: str
    name: str
    price: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    market_cap: Optional[float] = None
    pe_ttm: Optional[float] = None
    div_yield: Optional[float] = None
    expense_ratio: Optional[float] = None
    beta_5y: Optional[float] = None
    source: str = "unavailable"
    secondary_source: Optional[str] = None
    status: QuoteStatus = "unavailable"
    as_of: Optional[str] = None
    asset_class: Optional[str] = None


class Fundamentals(BaseModel):
    symbol: str
    name: str
    market_cap: Optional[float] = None
    pe_ttm: Optional[float] = None
    div_yield: Optional[float] = None
    expense_ratio: Optional[float] = None
    beta_5y: Optional[float] = None
    avg_volume: Optional[float] = None
    source: str = "unavailable"
    status: QuoteStatus = "unavailable"
    as_of: Optional[str] = None
    asset_class: Optional[str] = None


class SearchHit(BaseModel):
    symbol: str
    name: str
    asset_class: str


class Expiration(BaseModel):
    date: str
    dte: int
    kind: str
    near_expiry: bool
    earnings_highlight: bool = False


class OptionContract(BaseModel):
    """Every market datum is optional. A missing bid is reported as missing, never as 0.00.

    ``greeks_source`` / ``iv_source`` distinguish vendor-published values from
    locally computed Black-Scholes values so the UI can never present a
    model number as a live vendor number.
    """

    symbol: str
    strike: float
    side: Literal["call", "put"]
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    last: Optional[float] = None
    prev_close: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    greeks_source: ValueSource = "unavailable"
    iv_source: ValueSource = "unavailable"
    quote_as_of: Optional[str] = None


class OptionChain(BaseModel):
    symbol: str
    expiry: str
    spot: Optional[float] = None
    feed: DataFeed
    contracts: list[OptionContract]
    status: ChainStatus = "unavailable"
    source: str = "unavailable"
    spot_source: Optional[str] = None
    greeks_source: ValueSource = "unavailable"
    as_of: Optional[str] = None
    dte: Optional[int] = None
    expiry_valid: bool = True
    notes: list[str] = Field(default_factory=list)


class Bar(BaseModel):
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


class ChartSnapshot(BaseModel):
    symbol: str
    timeframe: str
    visible_from: str
    visible_to: str
    studies: list[str]
    captured_at: str
