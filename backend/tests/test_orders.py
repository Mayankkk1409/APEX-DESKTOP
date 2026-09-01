import pytest

from app.services.orders import account_impact, estimate_order_cost


def test_equity_order_cost() -> None:
    assert estimate_order_cost(10, 227.15) == 2271.50


def test_option_order_cost_uses_multiplier() -> None:
    assert estimate_order_cost(2, 4.50, asset_class="us_option") == 900.0


def test_order_cost_rejects_bad_qty() -> None:
    with pytest.raises(ValueError):
        estimate_order_cost(0, 10)


def test_account_impact_buy_sell() -> None:
    assert account_impact("buy", 100) == -100
    assert account_impact("sell", 100) == 100
