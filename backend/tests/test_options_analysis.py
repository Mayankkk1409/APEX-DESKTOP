"""Chain analysis and degradation tests.

Covers the paths a user can actually hit: no credentials, no entitlement, a cash index with
no listed chain, an expired expiry, an empty chain, a single-sided chain, zero open interest,
missing Greeks and missing quotes.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.adapters.alpaca import (
    AlpacaAdapter,
    _fill_model_greeks,
    _is_cash_index,
    _parse_snapshot,
    _side_from_occ,
    _strike_from_occ,
)
from app.adapters.demo import DemoAdapter
from app.analysis import black_scholes as bs
from app.config import Settings
from app.schemas.market import OptionChain, OptionContract
from app.services.options_analysis import (
    INFEASIBLE_SCENARIO_MSG,
    apply_execution_score_tiers,
    apply_recommended_contract,
    build_chain_analysis,
    days_to_expiry,
    execution_tier,
    pick_recommended_contract,
    strategy_selection_bucket,
)

TODAY = date(2026, 6, 1)
EXPIRY = "2026-07-01"  # 30 DTE from TODAY


def leg(strike: float, side: str = "call", **kw) -> OptionContract:
    base = dict(
        symbol=f"XYZ260701{side[0].upper()}{int(strike * 1000):08d}",
        strike=strike,
        side=side,
        bid=1.95,
        ask=2.05,
        last=2.0,
        prev_close=1.90,
        change=0.10,
        change_pct=0.0526,
        volume=800,
        open_interest=2000,
        iv=0.32,
        delta=0.55 if side == "call" else -0.45,
        gamma=0.02,
        theta=-0.04,
        vega=0.09,
        greeks_source="vendor",
        iv_source="vendor",
    )
    base.update(kw)
    return OptionContract(**base)


def chain(contracts: list[OptionContract], **kw) -> OptionChain:
    base = dict(
        symbol="XYZ",
        expiry=EXPIRY,
        spot=100.0,
        feed="opra",
        contracts=contracts,
        status="live",
        source="alpaca options snapshots (opra)",
        spot_source="alpaca",
        greeks_source="vendor",
        dte=30,
        expiry_valid=True,
    )
    base.update(kw)
    return OptionChain(**base)


def full_chain() -> OptionChain:
    legs: list[OptionContract] = []
    for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
        legs.append(leg(strike, "call"))
        legs.append(leg(strike, "put"))
    return chain(legs)


def analyse(c: OptionChain | None, **kw):
    kw.setdefault("symbol", "XYZ")
    kw.setdefault("expiry", EXPIRY)
    kw.setdefault("today", TODAY)
    return build_chain_analysis(c, **kw)


# ── happy path ────────────────────────────────────────────────────────────────


def test_full_chain_produces_every_card_and_a_row_per_contract() -> None:
    out = analyse(full_chain(), hv=0.30)
    assert out["symbol"] == "XYZ"
    assert out["expiry"] == EXPIRY
    assert out["dte"] == 30
    assert out["atm_strike"] == 100.0
    assert len(out["contracts"]) == 10
    assert all(row["verdict"] is not None for row in out["contracts"])

    ids = [c["id"] for c in out["cards"]]
    for expected in (
        "chain-provenance",
        "chain-spread",
        "chain-liquidity",
        "chain-volume",
        "greeks-delta",
        "greeks-theta",
        "greeks-delta-theta",
        "greeks-vega",
        "greeks-gamma",
        "chain-iv",
        "chain-positioning",
        "chain-vs-technical",
        "chain-gates",
    ):
        assert expected in ids, expected
    assert "candidates-buy" in ids or "candidates-sell" in ids
    assert "candidates-buy" not in ids or "candidates-sell" not in ids
    assert len(ids) == 14
    assert len(ids) == len(set(ids))
    # Cards must be substantive, not one-liners.
    assert all(len(c["body"]) > 200 for c in out["cards"])


def test_cards_quote_the_live_values_rather_than_a_template() -> None:
    out = analyse(full_chain(), hv=0.30)
    body = {c["id"]: c["body"] for c in out["cards"]}
    assert "XYZ" in body["chain-provenance"] and EXPIRY in body["chain-provenance"]
    assert "100.00" in body["chain-spread"] or "5.00%" in body["chain-spread"]  # spread on 2.00 mid
    assert "500" in body["chain-liquidity"]  # documented OI floor
    rec = out["recommendedContract"]
    assert rec is not None
    assert f"{rec['strike']:g}" in body["greeks-delta"]
    assert "recommended" in body["greeks-delta"].lower()
    assert "OPEN" in body["greeks-gamma"] or "closed" in body["greeks-gamma"]


def test_delta_card_ranks_leverage_by_elasticity_not_by_raw_delta() -> None:
    """Elasticity ranking lives in the chain-wide path; refocused cards centre on the recommended leg."""
    legs = [
        leg(75.0, "call", delta=0.97, bid=24.9, ask=25.1, last=25.0),
        leg(100.0, "call", delta=0.55, bid=1.95, ask=2.05, last=2.0),
    ]
    out = analyse(chain(legs), hv=0.30, selected_strategy="Bull Call Spread", direction="bullish", vol_signal="buy_premium")
    body = {c["id"]: c["body"] for c in out["cards"]}["greeks-delta"]
    rec = out["recommendedContract"]
    assert rec is not None
    assert f"{rec['strike']:g} call" in body
    assert "recommended" in body.lower()


def test_delta_card_says_so_when_elasticity_needs_a_spot_it_does_not_have() -> None:
    legs = [leg(100.0, "call", delta=0.6)]
    body = {c["id"]: c["body"] for c in analyse(chain(legs, spot=None), hv=0.30, selected_strategy="Bull Call Spread", direction="bullish")["cards"]}["greeks-delta"]
    assert "cannot be located" in body or "unavailable" in body.lower()


def test_vega_cap_card_states_that_short_legs_are_unaffected() -> None:
    """The cap is a long-premium rule; telling a premium seller an IV crush hurts is wrong."""
    out = analyse(full_chain(), hv=0.10)
    body = {c["id"]: c["body"] for c in out["cards"]}["greeks-vega"]
    assert "Short legs are unaffected" in body
    assert "short Vega" in body


def test_summary_structure_metrics() -> None:
    out = analyse(full_chain(), hv=0.30)
    s = out["summary"]
    assert s["contract_count"] == 10
    assert s["call_count"] == 5 and s["put_count"] == 5
    assert s["single_sided"] is False
    assert s["put_call_oi_ratio"] == pytest.approx(1.0)
    assert s["max_pain"]["strike"] == 100.0
    assert len(s["call_oi_walls"]) == 3
    assert s["median_spread_pct"] == pytest.approx(0.05)
    assert s["iv_skew_25d"] is not None


def test_thresholds_are_reported_so_the_ui_can_render_the_rule() -> None:
    out = analyse(full_chain(), spread_max_pct=0.15)
    assert out["thresholds"]["spread_max_pct_of_mid"] == 0.15
    assert out["thresholds"]["min_open_interest"] == 500
    assert "15%" in {c["id"]: c["body"] for c in out["cards"]}["chain-spread"]


# ── catalyst / Vega cap ───────────────────────────────────────────────────────


def test_catalyst_environment_arms_the_vega_cap_and_the_ui_state_is_exposed() -> None:
    out = analyse(full_chain(), hv=0.10)  # ATM IV 32% vs HV 10% = 22 points rich
    assert out["vega_cap"]["catalyst_environment"] is True
    assert out["vega_cap"]["blocks_long_premium"] is True
    assert out["summary"]["vega_cap_blocked"]
    assert "points above realised volatility" in out["vega_cap"]["reason"]

    overridden = analyse(full_chain(), hv=0.10, vega_cap_override=True)
    assert overridden["vega_cap"]["blocks_long_premium"] is False
    assert overridden["summary"]["vega_cap_blocked"] == []

    structured = analyse(full_chain(), hv=0.10, structure_absorbs_gamma=True)
    assert structured["vega_cap"]["blocks_long_premium"] is False


def test_no_catalyst_claim_without_a_volatility_reference() -> None:
    out = analyse(full_chain(), hv=None)
    assert out["vega_cap"]["catalyst_environment"] is False
    assert "realised volatility is unavailable" in out["vega_cap"]["reason"]
    assert out["summary"]["iv_rank_proxy"] is None
    assert "cannot be derived" in {c["id"]: c["body"] for c in out["cards"]}["chain-iv"]


def test_near_expiry_chain_flags_gamma_on_every_contract() -> None:
    out = analyse(chain(full_chain().contracts, dte=3), hv=0.30)
    assert out["dte"] == 3
    assert len(out["summary"]["gamma_flagged"]) == 10
    assert "OPEN" in {c["id"]: c["body"] for c in out["cards"]}["greeks-gamma"]


# ── edge cases a user can hit ─────────────────────────────────────────────────


def test_no_chain_at_all_claims_nothing() -> None:
    out = analyse(None)
    assert out["contracts"] == []
    assert out["summary"]["contract_count"] == 0
    assert out["cards"][0]["id"] == "chain-unavailable"
    assert "will not" in out["cards"][0]["body"]
    assert out["data_source"]["is_live"] is False


def test_empty_contract_list_degrades_with_the_vendor_reason() -> None:
    out = analyse(chain([], status="empty", notes=["Alpaca returned no option snapshots."]))
    assert out["cards"][0]["id"] == "chain-unavailable"
    assert "Vendor returned no contracts" in out["cards"][0]["body"]
    assert "Alpaca returned no option snapshots." in out["cards"][0]["body"]


def test_single_sided_chain_is_analysed_not_dropped() -> None:
    out = analyse(chain([leg(95.0), leg(100.0), leg(105.0)]), hv=0.30)
    s = out["summary"]
    assert s["single_sided"] is True
    assert s["call_count"] == 3 and s["put_count"] == 0
    assert s["put_call_volume_ratio"] is None
    assert s["iv_skew_25d"] is None
    assert "not computable" in {c["id"]: c["body"] for c in out["cards"]}["chain-volume"]


def test_zero_open_interest_expiry_screens_out_every_strike() -> None:
    out = analyse(chain([leg(100.0, open_interest=0), leg(100.0, "put", open_interest=0)]), hv=0.30)
    assert out["summary"]["verdict_counts"].get("screened_out") == 2
    assert out["summary"]["max_pain"] is None
    assert out["summary"]["call_oi_walls"] == []
    assert "not computable" in {c["id"]: c["body"] for c in out["cards"]}["chain-positioning"]


def test_missing_greeks_are_reported_as_ungradeable() -> None:
    naked = [
        leg(100.0, delta=None, gamma=None, theta=None, vega=None, greeks_source="unavailable"),
        leg(100.0, "put", delta=None, gamma=None, theta=None, vega=None, greeks_source="unavailable"),
    ]
    out = analyse(chain(naked, greeks_source="unavailable"), hv=0.30)
    assert out["summary"]["verdict_counts"].get("insufficient_data") == 2
    assert out["summary"]["greeks_available"] == 0
    assert out["data_source"]["missing_greeks"] == 2
    assert "not graded on Greek rules" in " ".join(out["data_source"]["caveats"])
    buy_card = {c["id"]: c["body"] for c in out["cards"]}["candidates-buy"]
    assert "does not lower the gates to produce a trade" in buy_card


def test_missing_quotes_do_not_become_zero_prices() -> None:
    out = analyse(chain([leg(100.0, bid=None, ask=None), leg(100.0, "put", bid=None, ask=None)]), hv=0.30)
    assert out["summary"]["quotes_two_sided"] == 0
    assert out["summary"]["median_spread_pct"] is None
    assert all(row["bid"] is None for row in out["contracts"])
    assert "No spread percentiles are computable" in {c["id"]: c["body"] for c in out["cards"]}["chain-spread"]


def test_mid_of_zero_is_hard_rejected_and_surfaced() -> None:
    out = analyse(chain([leg(100.0, bid=0.0, ask=0.0)]), hv=0.30)
    assert out["summary"]["verdict_counts"].get("rejected") == 1
    assert len(out["summary"]["hard_rejects"]) == 1


def test_very_wide_spreads_are_rejected_and_named_with_the_percentage() -> None:
    wide = [leg(95.0, bid=0.20, ask=3.00), leg(100.0), leg(105.0, bid=0.10, ask=5.00)]
    out = analyse(chain(wide), hv=0.30)
    assert out["summary"]["verdict_counts"].get("rejected") == 2
    body = {c["id"]: c["body"] for c in out["cards"]}["chain-spread"]
    assert "hard-reject" in body.lower()
    assert "%" in body


def test_no_spot_reference_disables_moneyness_without_crashing() -> None:
    out = analyse(chain(full_chain().contracts, spot=None), hv=0.30)
    assert out["atm_strike"] is None
    assert all(row["verdict"]["moneyness"] == "unknown" for row in out["contracts"])
    assert "cannot be located" in {c["id"]: c["body"] for c in out["cards"]}["greeks-delta"]


def test_zero_theta_across_the_chain_yields_no_ratio_claim() -> None:
    out = analyse(chain([leg(100.0, theta=0.0), leg(100.0, "put", theta=0.0)]), hv=0.30)
    body = {c["id"]: c["body"] for c in out["cards"]}["greeks-delta-theta"]
    assert "unavailable" in body
    assert out["summary"]["best_delta_theta"] == []


def test_expired_expiry_is_reported_as_invalid() -> None:
    out = analyse(chain(full_chain().contracts, expiry="2020-01-17", expiry_valid=False, dte=-2000), hv=0.30)
    assert out["expiry_valid"] is False
    assert "not a live, non-expired expiration" in " ".join(out["data_source"]["caveats"])


def test_simulated_chain_is_labelled_and_never_called_live() -> None:
    out = analyse(chain(full_chain().contracts, status="simulated", source="internal simulator"), hv=0.30)
    assert out["data_source"]["is_live"] is False
    assert out["data_source"]["label"] == "SIMULATED CHAIN — not live market data"
    assert "Do not trade from these numbers" in " ".join(out["data_source"]["caveats"])
    assert "TREAT EVERY NUMBER BELOW AS NON-EXECUTABLE" in {c["id"]: c["body"] for c in out["cards"]}["chain-provenance"]


def test_model_greeks_are_labelled_as_model() -> None:
    out = analyse(chain([leg(100.0, greeks_source="model"), leg(100.0, "put")]), hv=0.30)
    assert out["data_source"]["model_greeks"] == 1
    assert out["data_source"]["vendor_greeks"] == 1
    assert "not vendor-published Greeks" in " ".join(out["data_source"]["caveats"])


def test_days_to_expiry_handles_garbage() -> None:
    assert days_to_expiry("2026-07-01", TODAY) == 30
    assert days_to_expiry("not-a-date") is None
    assert days_to_expiry("") is None


# ── technical confirmation ────────────────────────────────────────────────────


def test_chain_confirms_a_matching_technical_read() -> None:
    calls_heavy = [leg(100.0, volume=5000), leg(100.0, "put", volume=100)]
    out = analyse(chain(calls_heavy), hv=0.30, technical={"direction": "bullish", "score": 81, "rsi": 62.0})
    body = {c["id"]: c["body"] for c in out["cards"]}["chain-vs-technical"]
    assert "CONFIRMATION" in body


def test_chain_contradiction_is_stated_plainly() -> None:
    puts_heavy = [leg(100.0, volume=100), leg(100.0, "put", volume=5000)]
    out = analyse(chain(puts_heavy), hv=0.30, technical={"direction": "bullish", "score": 81})
    body = {c["id"]: c["body"] for c in out["cards"]}["chain-vs-technical"]
    assert "CONTRADICTION" in body
    assert "Size down" in body


def test_agreement_is_not_scored_without_a_technical_read() -> None:
    out = analyse(full_chain(), hv=0.30, technical=None)
    body = {c["id"]: c["body"] for c in out["cards"]}["chain-vs-technical"]
    assert "cannot be scored" in body


# ── Alpaca adapter degradation ────────────────────────────────────────────────


def settings(**kw) -> Settings:
    base = dict(alpaca_api_key_id="", alpaca_api_secret_key="", app_secret_key="test-secret")
    base.update(kw)
    return Settings(**base)


@pytest.mark.asyncio
async def test_no_keys_degrades_with_an_explicit_reason() -> None:
    # Explicitly disable the offline simulator — conftest sets ALLOW_OPTIONS_SIMULATOR
    # for integration navigability, but this unit asserts the honest empty chain.
    adapter = AlpacaAdapter(settings(allow_options_simulator=False))
    expiry = (date.today() + timedelta(days=21)).isoformat()
    c = await adapter.option_chain("AAPL", expiry)
    assert c.status == "no_keys"
    assert "no_keys" in c.source
    assert c.contracts == [], "missing keys must not invent a Black-Scholes ladder"
    assert c.greeks_source == "unavailable"
    assert any("ALPACA_API_KEY_ID" in n for n in c.notes)
    assert any("Configure ALPACA_API_KEY_ID" in n or ".env" in n for n in c.notes)
    out = build_chain_analysis(c, symbol="AAPL", expiry=expiry)
    assert out["contracts"] == []
    assert out["data_source"]["status"] == "no_keys"
    assert "Configure Alpaca keys" in out["data_source"]["label"]


@pytest.mark.asyncio
async def test_options_simulator_only_when_flag_enabled() -> None:
    """ALLOW_OPTIONS_SIMULATOR=true is the only path that may fill a synthetic ladder."""
    adapter = AlpacaAdapter(settings(allow_options_simulator=True))
    expiry = (date.today() + timedelta(days=21)).isoformat()
    c = await adapter.option_chain("AAPL", expiry)
    assert c.status == "simulated"
    assert "no_keys" in c.source
    assert len(c.contracts) > 0
    assert c.greeks_source == "model"
    assert all(x.greeks_source == "model" for x in c.contracts)


@pytest.mark.asyncio
async def test_cash_index_reports_the_unsupported_underlying_before_credentials() -> None:
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))
    expiry = (date.today() + timedelta(days=21)).isoformat()
    c = await adapter.option_chain("SPX", expiry)
    assert c.status == "unsupported_underlying"
    assert "unsupported_underlying" in c.source
    assert c.contracts == [], "a cash index must not invent a synthetic ladder"
    assert c.greeks_source == "unavailable"
    assert any("cash-settled index" in n for n in c.notes)
    assert any("SPY" in n for n in c.notes)
    out = build_chain_analysis(c, symbol="SPX", expiry=expiry)
    assert out["contracts"] == []
    assert out["data_source"]["status"] == "unsupported_underlying"
    assert out["data_source"]["is_live"] is False
    assert out["cards"][0]["id"] == "chain-unavailable"


@pytest.mark.asyncio
async def test_cash_index_expirations_are_empty_not_simulated() -> None:
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))
    assert await adapter.expirations("SPX") == []


@pytest.mark.asyncio
async def test_expirations_paginate_with_gte_and_calls_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alpaca truncates without expiration_date_gte — discovery must force gte + pagination."""
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))
    calls: list[dict] = []
    d0 = (date.today() + timedelta(days=3)).isoformat()
    d1 = (date.today() + timedelta(days=10)).isoformat()
    d2 = (date.today() + timedelta(days=120)).isoformat()
    d3 = (date.today() + timedelta(days=200)).isoformat()
    expired = (date.today() - timedelta(days=30)).isoformat()

    async def fake_get(_base: str, path: str, params: dict | None = None):
        assert path == "/v2/options/contracts"
        assert params is not None
        calls.append(dict(params))
        page = int(params.get("page_token") or "0")
        if page == 0:
            return {
                "option_contracts": [
                    {"expiration_date": d0, "type": "call"},
                    {"expiration_date": d1, "type": "call"},
                    {"expiration_date": expired, "type": "call"},
                ],
                "next_page_token": "1",
            }
        if page == 1:
            return {
                "option_contracts": [
                    {"expiration_date": d2, "type": "call"},
                ],
                "next_page_token": "2",
            }
        return {
            "option_contracts": [
                {"expiration_date": d3, "type": "call"},
            ],
            "next_page_token": None,
        }

    monkeypatch.setattr(adapter, "_get", fake_get)
    out = await adapter.expirations("AAPL")
    assert calls, "must hit the contracts endpoint"
    assert calls[0]["type"] == "call"
    assert calls[0]["limit"] == 1000
    assert "expiration_date_gte" in calls[0]
    assert len(calls) == 3, "must follow every next_page_token until exhausted"
    dates = [e.date for e in out]
    assert dates == [d0, d1, d2, d3]
    assert expired not in dates


@pytest.mark.asyncio
async def test_expirations_with_keys_do_not_fall_back_to_demo_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))

    async def empty_get(_base: str, path: str, params: dict | None = None):
        return {"option_contracts": [], "next_page_token": None}

    monkeypatch.setattr(adapter, "_get", empty_get)
    assert await adapter.expirations("AAPL") == []


@pytest.mark.asyncio
async def test_option_snapshots_paginate_for_selected_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))
    calls: list[dict] = []

    async def fake_status(_base: str, path: str, params: dict | None = None):
        assert "snapshots" in path
        assert params is not None
        assert params["expiration_date"] == "2026-09-18"
        calls.append(dict(params))
        page = int(params.get("page_token") or "0")
        if page == 0:
            return 200, {
                "snapshots": {"AAPL260918C00100000": {"latestQuote": {"bp": 1.0, "ap": 1.1}}},
                "next_page_token": "1",
            }
        return 200, {
            "snapshots": {"AAPL260918P00100000": {"latestQuote": {"bp": 0.9, "ap": 1.0}}},
            "next_page_token": None,
        }

    monkeypatch.setattr(adapter, "_get_with_status", fake_status)
    snaps, status = await adapter._option_snapshots("AAPL", "2026-09-18")
    assert status == 200
    assert len(calls) == 2
    assert set(snaps) == {"AAPL260918C00100000", "AAPL260918P00100000"}


@pytest.mark.asyncio
async def test_expired_expiry_is_refused_before_any_vendor_call() -> None:
    adapter = AlpacaAdapter(settings(alpaca_api_key_id="k", alpaca_api_secret_key="s"))
    c = await adapter.option_chain("AAPL", "2020-01-17")
    assert c.expiry_valid is False
    assert any("not a valid, non-expired expiration" in n for n in c.notes)
    out = build_chain_analysis(c, symbol="AAPL", expiry="2020-01-17")
    assert "not a live, non-expired expiration" in " ".join(out["data_source"]["caveats"])


@pytest.mark.asyncio
async def test_malformed_expiry_does_not_raise() -> None:
    adapter = AlpacaAdapter(settings())
    c = await adapter.option_chain("AAPL", "next friday")
    assert c.contracts == []
    assert c.expiry_valid is False
    assert build_chain_analysis(c, symbol="AAPL", expiry="next friday")["cards"][0]["id"] == "chain-unavailable"


@pytest.mark.asyncio
async def test_demo_chain_is_always_labelled_simulated() -> None:
    demo = DemoAdapter()
    exps = await demo.expirations("AAPL")
    c = await demo.option_chain("AAPL", exps[2].date)
    assert c.status == "simulated"
    assert c.greeks_source == "model"
    assert all(x.greeks_source == "model" for x in c.contracts)
    out = build_chain_analysis(c, symbol="AAPL", expiry=c.expiry, hv=0.28)
    assert out["data_source"]["is_live"] is False
    assert len(out["cards"]) == 14


@pytest.mark.asyncio
async def test_demo_chain_greeks_agree_with_its_own_quotes() -> None:
    """The simulated ladder must be internally consistent.

    Every rule on the screen runs on these numbers, so a Delta that disagrees with the quoted
    price and IV would make the analysis narrate a chain that could not exist.
    """
    demo = DemoAdapter()
    exps = await demo.expirations("AAPL")
    chain_out = await demo.option_chain("AAPL", exps[4].date)
    assert chain_out.spot is not None and chain_out.dte is not None
    years = bs.year_fraction(chain_out.dte)
    checked = 0
    for c in chain_out.contracts:
        assert c.iv is not None and c.delta is not None and c.rho is not None
        g = bs.greeks(spot=chain_out.spot, strike=c.strike, years=years, vol=c.iv, side=c.side)
        assert g is not None
        mid = (c.bid + c.ask) / 2 if c.bid is not None and c.ask is not None else None
        assert mid is not None
        assert mid == pytest.approx(g.price, abs=0.02)
        assert c.delta == pytest.approx(g.delta, abs=1e-3)
        assert c.theta == pytest.approx(g.theta, abs=1e-3)
        assert c.vega == pytest.approx(g.vega, abs=1e-3)
        checked += 1
    assert checked >= 20


@pytest.mark.asyncio
async def test_demo_chain_exercises_the_documented_gates() -> None:
    """A simulated chain where nothing ever fails would flatter the rule engine.

    Real ladders have illiquid wings, so the fallback chain has them too — otherwise the
    screen never shows a trader what a rejected strike looks like.
    """
    demo = DemoAdapter()
    exps = await demo.expirations("AAPL")
    chain_out = await demo.option_chain("AAPL", exps[4].date)
    out = build_chain_analysis(chain_out, symbol="AAPL", expiry=chain_out.expiry, hv=0.26)
    counts = out["summary"]["verdict_counts"]
    assert counts.get("rejected", 0) > 0, "no wing is wide enough to trip the §5.5 cap"
    assert counts.get("buy_candidate", 0) > 0, "no strike clears the §5.1 buy profile"
    assert counts.get("sell_candidate", 0) > 0, "no strike fits the §5.1 short-leg profile"
    # Strikes are on a listed increment, not offset from an arbitrary spot.
    strikes = sorted({c.strike for c in chain_out.contracts})
    steps = {round(b - a, 2) for a, b in zip(strikes, strikes[1:])}
    assert len(steps) == 1 and steps.pop() in {0.5, 1.0, 2.5, 5.0, 10.0, 20.0}


@pytest.mark.asyncio
async def test_demo_chain_rejects_a_malformed_expiry() -> None:
    c = await DemoAdapter().option_chain("AAPL", "2026-13-45")
    assert c.contracts == []
    assert c.expiry_valid is False


# ── snapshot parsing ──────────────────────────────────────────────────────────


def test_occ_symbol_parsing() -> None:
    assert _side_from_occ("AAPL260717C00150000", None) == "call"
    assert _side_from_occ("AAPL260717P00150000", None) == "put"
    assert _side_from_occ("AAPL260717C00150000", "put") == "put"
    assert _side_from_occ("SHORT", None) is None
    assert _strike_from_occ("AAPL260717C00150000") == pytest.approx(150.0)
    assert _strike_from_occ("BAD") is None


def test_snapshot_merges_contract_metadata_and_never_invents_zeros() -> None:
    snap = {
        "latestQuote": {"bp": 2.10, "ap": 2.20, "bs": 4, "as": 7, "t": "2026-06-01T14:30:00Z"},
        "latestTrade": {"p": 2.15},
        "dailyBar": {"v": 1234, "c": 2.15},
        "prevDailyBar": {"c": 2.00},
        "greeks": {"delta": 0.52, "gamma": 0.03, "theta": -0.05, "vega": 0.11, "rho": 0.01},
        "impliedVolatility": 0.31,
    }
    meta = {"strike_price": 150.0, "type": "call", "open_interest": "7400"}
    c = _parse_snapshot("AAPL260717C00150000", snap, meta)
    assert c is not None
    assert (c.strike, c.side, c.open_interest) == (150.0, "call", 7400)
    assert c.bid == 2.10 and c.ask == 2.20 and c.bid_size == 4 and c.ask_size == 7
    assert c.volume == 1234
    assert c.change == pytest.approx(0.15)
    assert c.change_pct == pytest.approx(0.075)
    assert c.greeks_source == "vendor" and c.iv_source == "vendor"


def test_snapshot_without_greeks_or_quotes_keeps_them_absent() -> None:
    c = _parse_snapshot("AAPL260717P00150000", {}, {"strike_price": 150.0, "type": "put"})
    assert c is not None
    assert (c.bid, c.ask, c.delta, c.iv, c.volume, c.open_interest) == (None,) * 6
    assert c.greeks_source == "unavailable"


def test_unidentifiable_snapshot_is_dropped() -> None:
    assert _parse_snapshot("JUNK", {}, None) is None
    assert _parse_snapshot("AAPL260717C00150000", "not a dict") is None


def test_model_greeks_fill_only_where_the_vendor_did_not_publish() -> None:
    vendor = _parse_snapshot(
        "AAPL260717C00150000",
        {"greeks": {"delta": 0.9, "gamma": 0.001, "theta": -0.01, "vega": 0.02, "rho": 0.0}, "impliedVolatility": 0.3},
        {"strike_price": 150.0, "type": "call"},
    )
    bare = _parse_snapshot(
        "AAPL260717C00160000",
        {"latestQuote": {"bp": 4.90, "ap": 5.10}},
        {"strike_price": 160.0, "type": "call"},
    )
    assert vendor is not None and bare is not None
    _fill_model_greeks([vendor, bare], spot=155.0, dte=46)
    assert vendor.delta == 0.9 and vendor.greeks_source == "vendor"
    assert bare.greeks_source == "model" and bare.iv_source == "model"
    assert bare.delta is not None and 0.0 < bare.delta < 1.0
    assert bare.theta is not None and bare.theta < 0


def test_model_greeks_are_skipped_without_a_spot_or_a_price() -> None:
    bare = _parse_snapshot("AAPL260717C00160000", {}, {"strike_price": 160.0, "type": "call"})
    assert bare is not None
    _fill_model_greeks([bare], spot=None, dte=30)
    assert bare.greeks_source == "unavailable"
    _fill_model_greeks([bare], spot=155.0, dte=30)
    assert bare.greeks_source == "unavailable"  # no mid and no IV to solve from


def test_cash_index_detection() -> None:
    assert _is_cash_index("spx") and _is_cash_index("NDX") and _is_cash_index("VIX")
    assert not _is_cash_index("SPY") and not _is_cash_index("AAPL")


# ── Black-Scholes ─────────────────────────────────────────────────────────────


def test_call_and_put_greeks_have_the_documented_signs_and_magnitudes() -> None:
    call = bs.greeks(spot=100.0, strike=100.0, years=0.25, vol=0.30, side="call")
    put = bs.greeks(spot=100.0, strike=100.0, years=0.25, vol=0.30, side="put")
    assert call is not None and put is not None
    assert 0.4 < call.delta < 0.6
    assert -0.6 < put.delta < -0.4
    assert call.gamma > 0 and put.gamma > 0
    assert call.theta < 0 and put.theta < 0
    assert call.vega > 0 and put.vega > 0
    # Put-call parity at a zero rate: C - P = S - K = 0.
    assert call.price - put.price == pytest.approx(0.0, abs=1e-6)


def test_deep_itm_and_otm_delta_saturate() -> None:
    itm = bs.greeks(spot=200.0, strike=100.0, years=0.25, vol=0.30, side="call")
    otm = bs.greeks(spot=50.0, strike=100.0, years=0.25, vol=0.30, side="call")
    assert itm is not None and otm is not None
    assert itm.delta > 0.98
    assert otm.delta < 0.02


def test_zero_dte_does_not_divide_by_zero() -> None:
    g = bs.greeks(spot=100.0, strike=100.0, years=0.0, vol=0.30, side="call")
    assert g is not None and g.gamma > 0


def test_degenerate_inputs_return_none_rather_than_a_plausible_zero() -> None:
    assert bs.greeks(spot=0.0, strike=100.0, years=0.25, vol=0.3, side="call") is None
    assert bs.greeks(spot=100.0, strike=0.0, years=0.25, vol=0.3, side="call") is None
    assert bs.greeks(spot=100.0, strike=100.0, years=0.25, vol=0.0, side="call") is None


def test_implied_vol_round_trips() -> None:
    target = bs.greeks(spot=100.0, strike=105.0, years=0.5, vol=0.42, side="call")
    assert target is not None
    solved = bs.implied_vol(price=target.price, spot=100.0, strike=105.0, years=0.5, side="call")
    assert solved == pytest.approx(0.42, abs=1e-3)


def test_implied_vol_refuses_impossible_prices() -> None:
    assert bs.implied_vol(price=0.0, spot=100.0, strike=100.0, years=0.5, side="call") is None
    assert bs.implied_vol(price=1e6, spot=100.0, strike=100.0, years=0.5, side="call") is None
    # Below intrinsic is not solvable.
    assert bs.implied_vol(price=1.0, spot=200.0, strike=100.0, years=0.5, side="call") is None


# ── recommended contract (strategy scoring) ───────────────────────────────────


def test_strategy_selection_bucket_maps_playbook_labels() -> None:
    assert strategy_selection_bucket("Bull Call Spread") == ("buy", "call")
    assert strategy_selection_bucket("Bear Put Spread") == ("buy", "put")
    assert strategy_selection_bucket("Short Iron Condor") == ("sell", None)
    assert strategy_selection_bucket("NO TRADE — Insufficient Conviction") == (None, None)


def test_recommended_contract_picks_highest_buy_score_for_bull_call_spread() -> None:
    legs = [
        leg(100.0, "call", delta=0.58, theta=-0.02),
        leg(105.0, "call", delta=0.56, theta=-0.04),
        leg(100.0, "put"),
        leg(105.0, "put"),
    ]
    out = analyse(
        chain(legs),
        hv=0.30,
        selected_strategy="Bull Call Spread",
        direction="bullish",
        vol_signal="buy_premium",
    )
    rec = out["recommendedContract"]
    assert rec is not None
    assert rec["strike"] == 100.0
    assert rec["side"] == "call"
    assert rec["expiry"] == EXPIRY
    assert rec["symbol"] == "XYZ"


def test_recommended_contract_can_be_atm_when_it_scores_best() -> None:
    """Scoring — not a visual rule — decides the highlight; ATM wins when it ranks first."""
    legs = [
        leg(100.0, "call", delta=0.58, theta=-0.02),
        leg(105.0, "call", delta=0.56, theta=-0.05),
        leg(100.0, "put"),
        leg(105.0, "put"),
    ]
    out = analyse(
        chain(legs, spot=100.0),
        hv=0.30,
        selected_strategy="Bull Call Spread",
        direction="bullish",
        vol_signal="buy_premium",
    )
    rec = out["recommendedContract"]
    assert rec is not None
    assert rec["strike"] == out["atm_strike"] == 100.0
    assert rec["side"] == "call"


def test_no_trade_strategy_yields_no_recommended_contract() -> None:
    out = analyse(full_chain(), hv=0.30, selected_strategy="NO TRADE — Insufficient Conviction")
    assert out["recommendedContract"] is None


def test_apply_recommended_contract_refocuses_greek_cards() -> None:
    base = analyse(full_chain(), hv=0.30, selected_strategy="NO TRADE — Insufficient Conviction")
    assert base["recommendedContract"] is None
    focused = apply_recommended_contract(
        base,
        selected_strategy="Bull Call Spread",
        direction="bullish",
        vol_signal="buy_premium",
    )
    assert focused["recommendedContract"] is not None
    delta_card = next(c for c in focused["cards"] if c["id"] == "greeks-delta")
    strike = focused["recommendedContract"]["strike"]
    assert f"{strike:g} call" in delta_card["body"]
    assert "recommended" in delta_card["body"].lower()


# ── execution score tiers ─────────────────────────────────────────────────────


def test_execution_tier_bands() -> None:
    assert execution_tier(40) == "blocked"
    assert execution_tier(50) == "blocked"
    assert execution_tier(51) == "caution"
    assert execution_tier(72) == "auto_exec"
    assert execution_tier(71) == "caution"


def test_blocked_tier_strips_recommended_contract_and_surfaces_message() -> None:
    base = analyse(full_chain(), hv=0.30, selected_strategy="Bull Call Spread", direction="bullish", vol_signal="buy_premium")
    assert base["recommendedContract"] is not None
    out = apply_execution_score_tiers(
        base,
        48.0,
        selected_strategy="NO TRADE — Insufficient Conviction",
        direction="bullish",
        vol_signal="buy_premium",
    )
    assert out["execution_tier"] == "blocked"
    assert out["recommendedContract"] is None
    assert out["cards"][0]["id"] == "chain-infeasible"
    assert INFEASIBLE_SCENARIO_MSG in out["cards"][0]["body"]


def test_caution_tier_keeps_recommended_highlight() -> None:
    base = analyse(full_chain(), hv=0.30, selected_strategy="NO TRADE — Insufficient Conviction")
    out = apply_execution_score_tiers(
        base,
        65.0,
        selected_strategy="NO TRADE — Insufficient Conviction",
        direction="bullish",
        vol_signal="buy_premium",
    )
    assert out["execution_tier"] == "caution"
    assert out["recommendedContract"] is not None


def test_auto_exec_tier_keeps_recommended_for_full_doc_strategy() -> None:
    base = analyse(full_chain(), hv=0.30, selected_strategy="NO TRADE — Insufficient Conviction")
    out = apply_execution_score_tiers(
        base,
        81.0,
        selected_strategy="Bull Call Spread",
        direction="bullish",
        vol_signal="buy_premium",
    )
    assert out["execution_tier"] == "auto_exec"
    assert out["recommendedContract"] is not None
