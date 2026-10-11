"""Queued orders wait for a real price. They do not invent one."""

from datetime import datetime, timezone

from app.services.order_queue import broker_unconfirmed, price_gap, queue_deadline, session_open


def test_only_a_missing_price_can_queue() -> None:
    assert price_gap("No current price is available. No order was sent. Refresh the quote and try again.")
    assert price_gap(
        "A current price for this strategy is unavailable. No order was sent, "
        "and the strategy was not split into separate orders."
    )
    assert price_gap("Live mid is unavailable, so a limit at mid cannot be priced.")
    assert not price_gap("Insufficient buying power. The account cannot cover the order.")
    assert not price_gap("Leg count 0 does not match the template.")
    assert not price_gap("This price is more than 5 minutes old. No order was sent.")
    assert not price_gap("We couldn't confirm when this price was quoted. No order was sent.")
    assert not price_gap("Bid/ask spread is 12% of mid, wider than the 10% cap.")
    assert not price_gap("No current price is available. Insufficient buying power.")
    assert not broker_unconfirmed("No current price is available. No order was sent.")


def test_broker_hold_is_queued_and_not_a_price_gap() -> None:
    text = (
        "The broker received this order but has not confirmed a fill. "
        "Check its status before sending another order."
    )
    assert broker_unconfirmed(text)
    assert not price_gap(text)
    assert not broker_unconfirmed("Insufficient buying power. The account cannot cover the order.")


def test_weekend_is_closed_and_monday_session_is_open() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)  # 10:00 New York
    assert session_open(saturday) is False
    assert session_open(monday) is True


def test_saturday_queue_lasts_through_monday_close_not_forever() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    deadline = queue_deadline(saturday, ["2026-10-16"])
    assert deadline.isoformat().startswith("2026-10-12")
    assert deadline.hour in {20, 21}  # 16:00 New York in October is 20:00 UTC


def test_an_earlier_contract_expiry_caps_the_queue() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    deadline = queue_deadline(saturday, ["2026-10-09"])
    assert deadline.date().isoformat() == "2026-10-09"
