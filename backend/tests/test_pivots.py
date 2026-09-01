from app.analysis.indicators import pivot_points


def test_pivot_ladder_r5_s5() -> None:
    p = pivot_points(210.0, 190.0, 200.0)
    assert p["r5"] > p["r4"] > p["r3"] > p["r2"] > p["r1"] > p["pp"]
    assert p["s5"] < p["s4"] < p["s3"] < p["s2"] < p["s1"] < p["pp"]
    # Classic identity: R3 = High + 2*(PP-Low)
    pp = (210.0 + 190.0 + 200.0) / 3.0
    assert abs(p["r3"] - (210.0 + 2 * (pp - 190.0))) < 1e-9
    assert abs(p["r5"] - (210.0 + 4 * (pp - 190.0))) < 1e-9
