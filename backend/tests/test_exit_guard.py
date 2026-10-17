from app.services.exit_guard import exit_trigger
from app.services.sentiment_layer import _earnings_alert


def test_a_long_closes_at_the_stop_or_the_target() -> None:
    assert exit_trigger("buy", 90, 95, 110) == "stop"
    assert exit_trigger("buy", 110, 95, 110) == "take_profit"
    assert exit_trigger("buy", 100, 95, 110) is None
    assert exit_trigger("sell", 80, 95, 110) is None


def test_a_past_earnings_date_is_not_a_countdown() -> None:
    alert = _earnings_alert({"earnings_calendar": {"dte": -1, "next_date": "2026-10-13", "source": "newsroom"}})
    assert alert["active"] is False
    assert alert["message"] == "Earnings passed (2026-10-13)."
