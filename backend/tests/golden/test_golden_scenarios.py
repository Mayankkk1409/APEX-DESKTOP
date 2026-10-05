"""Lock the Change 11 European model grid. It is one chain, not five recorded chains.

Inputs: spot 100, strikes 94 and 106, post-event IV 28%, 7 and 21 days.
The chain debit 0.61 is what the Change 11 builder produces from front IV 55% and back IV 36%.
The second row uses the report's stated debit 0.6172 and expected move 6.08.
Change 11 REPORT.md rounded a nearby table. Those printed cents are not asserted.
Gamma Trampoline™ is still not counted as five recorded market chains.
"""

from __future__ import annotations

from app.services.apex_strategy import DOUBLE_CALENDAR_NAME, GAMMA_TRAMPOLINE_NAME, classifier_label
from app.strategies.payoffs.core import gamma_move_table

_CHAIN_POINTS = (
    (0.0, 15.16),
    (0.5, 59.89),
    (-0.5, 44.47),
    (1.0, 169.82),
    (-1.0, 143.40),
    (1.5, 51.18),
    (-1.5, 22.91),
    (2.0, -13.77),
    (-2.0, -34.92),
)
_STATED_POINTS = (
    (0.0, 14.44),
    (0.5, 59.23),
    (-0.5, 43.80),
    (1.0, 168.90),
    (-1.0, 142.46),
    (1.5, 50.27),
    (-1.5, 22.01),
    (2.0, -14.61),
    (-2.0, -35.73),
)


def test_change11_model_grid_and_label() -> None:
    assert classifier_label(eligible=True) == GAMMA_TRAMPOLINE_NAME
    assert classifier_label(eligible=False) == DOUBLE_CALENDAR_NAME
    cases = (
        (0.61, 6.0758, _CHAIN_POINTS),
        (0.6172, 6.08, _STATED_POINTS),
    )
    for debit, move, points in cases:
        table = gamma_move_table(
            spot=100.0,
            call_strike=106,
            put_strike=94,
            net_debit=debit,
            front_dte_days=7,
            back_dte_days=21,
            post_event_iv=0.28,
            expected_move=move,
        )
        rows = {row["move"]: row["pnl"] for row in table["rows"]["1.00"]}
        assert len(points) >= 5
        for multiple, expected in points:
            assert abs(rows[multiple] - expected) <= 0.01, (debit, multiple, rows[multiple], expected)
