from app.analysis.supertrend import compute_supertrend, true_range


def test_true_range() -> None:
    assert true_range(12, 10, 11) == 2


def test_supertrend_atr10_factor3_direction() -> None:
    # steadily rising series should finish bullish
    closes = [100 + i * 0.8 for i in range(40)]
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    pts = compute_supertrend(highs, lows, closes, atr_length=10, factor=3.0)
    assert len(pts) == 40
    assert pts[-1].direction == 1
    assert pts[-1].supertrend < closes[-1]

    # steadily falling series should finish bearish
    closes_dn = [140 - i * 0.9 for i in range(40)]
    highs_dn = [c + 0.3 for c in closes_dn]
    lows_dn = [c - 0.3 for c in closes_dn]
    down = compute_supertrend(highs_dn, lows_dn, closes_dn, atr_length=10, factor=3.0)
    assert down[-1].direction == -1
