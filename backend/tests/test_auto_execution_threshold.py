"""Saved auto-execution minimum is the only composite score gate."""

from pathlib import Path

from app.services.scan_engine import _restore_scored_strategy_layer
from app.services.strategy_engine import strategy_decision
from app.services.strategy_recommendation import allows_auto_execution

_RANKED = dict(
    direction="neutral",
    vol_signal="sell_premium",
    rsi=50.0,
    iv=0.30,
    hv=0.28,
    tech_score=70.0,
    confirmed_pattern_count=1,
)


def test_threshold_35_arms_at_36_not_at_34() -> None:
    assert allows_auto_execution(
        "Bull Call Spread",
        execution_tier="blocked",
        composite=36,
        auto_exec_threshold=35,
    )
    assert not allows_auto_execution(
        "Bull Call Spread",
        execution_tier="auto_exec",
        composite=34,
        auto_exec_threshold=35,
    )


def test_threshold_85_does_not_arm_at_72() -> None:
    assert not allows_auto_execution(
        "Bull Call Spread",
        execution_tier="auto_exec",
        composite=72,
        auto_exec_threshold=85,
    )


def test_threshold_40_arms_at_40() -> None:
    assert allows_auto_execution(
        "Bull Call Spread",
        execution_tier="caution",
        composite=40,
        auto_exec_threshold=40,
    )


def test_undefined_risk_does_not_arm_above_threshold() -> None:
    assert not allows_auto_execution(
        "Naked Call",
        execution_tier="auto_exec",
        composite=99,
        auto_exec_threshold=35,
    )


def test_saved_minimum_is_inclusive() -> None:
    assert allows_auto_execution(
        "Bull Put Spread (credit)",
        execution_tier="caution",
        composite=35,
        auto_exec_threshold=35,
    )


def test_above_threshold_keeps_strategy_and_arms() -> None:
    decision = strategy_decision(**_RANKED, composite=71, auto_exec_threshold=70)
    assert decision.best_match == "Short Iron Condor"
    assert decision.auto_exec_eligible is True


def test_equal_threshold_keeps_strategy_and_arms() -> None:
    decision = strategy_decision(**_RANKED, composite=70, auto_exec_threshold=70)
    assert decision.best_match == "Short Iron Condor"
    assert decision.auto_exec_eligible is True


def test_below_threshold_keeps_strategy_and_does_not_arm() -> None:
    decision = strategy_decision(**_RANKED, composite=62, auto_exec_threshold=70)
    assert decision.best_match == "Short Iron Condor"
    assert decision.auto_exec_eligible is False
    assert decision.gate_reason is None


def test_score_72_does_not_block_when_user_minimum_is_40() -> None:
    assert allows_auto_execution(
        "Short Iron Condor",
        execution_tier="caution",
        composite=72,
        auto_exec_threshold=40,
    )
    decision = strategy_decision(**_RANKED, composite=72, auto_exec_threshold=40)
    assert decision.best_match == "Short Iron Condor"
    assert decision.auto_exec_eligible is True


def test_restored_layer_keeps_the_real_score_sentence() -> None:
    layer = {
        "composite_score": 51.0,
        "execution_tier": "auto_exec",
        "why_recommended": (
            "Composite 51.0/100 meets your auto-execution threshold (40). "
            "Technical bias bullish (score 70)."
        ),
    }
    _restore_scored_strategy_layer(layer, 30, 40)
    assert layer["composite_score"] == 30
    assert layer["execution_tier"] == "caution"
    assert layer["why_recommended"].startswith(
        "Composite 30.0/100 — manual review required below your auto-execution threshold (40)."
    )
    assert "Technical bias bullish" in layer["why_recommended"]
    assert "51.0" not in layer["why_recommended"]


def test_score_66_clears_saved_minimum_40() -> None:
    decision = strategy_decision(**_RANKED, composite=66, auto_exec_threshold=40)
    assert decision.auto_exec_eligible is True
    assert decision.best_match == "Short Iron Condor"
    from app.services.strategy_recommendation import auto_exec_status_line, is_defined_risk_strategy

    line = auto_exec_status_line(66, 40, defined_risk=is_defined_risk_strategy(decision.best_match))
    assert line == "Composite score 66.0 · Your auto-execute minimum 40.0 · Auto-execute eligible"


def test_score_below_saved_minimum_keeps_the_strategy() -> None:
    decision = strategy_decision(**_RANKED, composite=39, auto_exec_threshold=40)
    assert decision.best_match == "Short Iron Condor"
    assert decision.auto_exec_eligible is False


def test_mild_iv_hv_ratio_does_not_rename_the_strategy() -> None:
    from app.services.strategy_recommendation import extreme_iv_overhang

    assert extreme_iv_overhang(0.2334, 0.224578) is False
    assert extreme_iv_overhang(0.2549, 0.216802) is False
    decision = strategy_decision(
        **{**_RANKED, "iv": 0.2334, "hv": 0.224578},
        composite=66,
        auto_exec_threshold=40,
    )
    assert decision.auto_exec_eligible is True
    assert "IV Crush" not in decision.best_match
    assert not any("1.35" in note for note in decision.risk_notes)


def test_low_score_does_not_replace_strategy_with_no_trade() -> None:
    decision = strategy_decision(**_RANKED, composite=45, auto_exec_threshold=85)
    assert decision.best_match == "Short Iron Condor"
    assert "NO TRADE" not in decision.best_match


def test_recommendation_copy_does_not_use_veto_labels() -> None:
    root = Path(__file__).resolve().parents[2]
    needles = (
        "NO TRADE",
        "Wait for IV Crush",
        "Stand aside",
        "Extreme IV overhang",
        "No Trade / Insufficient Conviction",
    )
    roots = [root / "backend" / "app" / "services", root / "frontend" / "src"]
    hits: list[str] = []
    for base in roots:
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".py", ".ts", ".tsx"}:
                continue
            if ".test." in path.name or ".spec." in path.name or path.name.endswith("_test.py"):
                continue
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                if needle.lower() in text.lower():
                    hits.append(f"{path.relative_to(root)}: {needle}")
    assert hits == []


def test_forbidden_blocker_string_is_absent_from_sources() -> None:
    root = Path(__file__).resolve().parents[2]
    needle = "BELOW EXECUTION THRESHOLD"
    roots = [
        root / "backend" / "app",
        root / "frontend" / "src",
    ]
    hits: list[str] = []
    for base in roots:
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".py", ".ts", ".tsx"}:
                continue
            if ".test." in path.name or ".spec." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            if needle in text:
                hits.append(str(path.relative_to(root)))
    assert hits == []
