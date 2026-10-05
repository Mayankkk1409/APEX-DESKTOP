# Change 4 — Always show a recommendation

The saved auto-execution minimum decides how an order is placed. It does not decide whether a recommendation appears.

## Root cause

A low composite was a selection gate, not just a placement gate.

1. `recommend_strategy` returned `No Trade / Insufficient Conviction` whenever the composite was at or below 50, throwing away the ranked defined-risk structure. Scores under 72 were a second gate: that band forced `auto_exec_eligible` off even when the saved minimum was lower (for example 40).
2. `build_strategy_layer` then replaced any strategy at or below 50 with an empty “Not tradeable” payload and no legs. `scan_engine` copied that into risk review as `execution_tier: blocked` and `allows_execution: false`.
3. Deep Scan hid the order form behind “Execution is blocked for this scan (composite ≤50 or no tradeable options legs).” The strategy slide also relabeled any score under 50 as No Trade and dropped the legs. The score slide badge read “Below execution threshold.”

The all-caps token `BELOW EXECUTION THRESHOLD` was not stored in the tree. That score-slide sentence, the ≤50 No Trade replacement, and the blocked order panel were the blocker.

New accounts still default the minimum to 85. After that, only the saved value is the score threshold. IV crush (only when IV and HV are real and IV > HV × 1.35), earnings blackout, and a wide spread still explain risk. They no longer drop legs that were built for the ranked structure.

## Behavior

- Score **above** or **equal to** the saved minimum, global auto-execute on, defined-risk structure: acknowledging the thesis auto-submits.
- Score **below** the saved minimum: the structure and its legs stay on screen, and Place Trade stays enabled. The note is neutral, for example “Manual confirmation required (score 62 vs. your auto-execute minimum 70).”
- A score of 72 does not block when the saved minimum is 40.

## Files

- `backend/app/services/strategy_recommendation.py` — stop a low score, and stop 72, from replacing the ranked strategy.
- `backend/app/services/scan_engine.py` — keep legs and the real score; arm auto-submit only from the saved minimum and defined risk.
- `backend/app/services/strategy_engine.py` — score-slide copy no longer tells the trader to hold for 72 or that the playbook was skipped.
- `frontend/src/lib/riskReview.ts` — placement helper (auto-ack vs enabled Place Trade vs neutral note).
- `frontend/src/pages/DeepScan.tsx` — risk-review order region only.
- `frontend/src/components/StrategyScan.tsx` — do not replace a legged recommendation because the score is low.
- `frontend/src/components/ApexScoreScan.tsx` — remove the below-threshold badge.
- Settings disclaimer was already the new-account default of 85, with no below-threshold or 72 wording, so `Settings.tsx` was not edited.

## Tests

- `backend/tests/test_auto_execution_threshold.py` — above, equal, and below the saved minimum; 72 does not block at a minimum of 40; low score stays a ranked strategy; forbidden string absent from app sources; restored score sentence keeps the decimal in `51.0` from corrupting the rest of the line.
- `backend/tests/test_strategy_engine.py` and `backend/tests/test_apex_upgrade.py` — low composites now expect the ranked structure (Short Iron Condor, Bull Call Spread, or Married Put on the conservative profile).
- `frontend/src/lib/riskReview.test.ts` — same placement cases, plus the forbidden string absent from the order-path sources.
- `frontend/src/components/scanSlides.test.tsx` — a score under 50 no longer forces the No Trade label; a No Trade label that still has legs shows those legs.

`python3 -m pytest tests/test_auto_execution_threshold.py tests/test_strategy_engine.py tests/test_apex_upgrade.py` and the frontend vitest files above passed. This session had no browser runner, so the Deep Scan order panel was not clicked in a live window.
