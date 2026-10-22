# Current scene evidence

This directory contains only the scene evidence used by the current autonomous
inspection experiment and the small bbox review utility.

- `scene_evidence_current/` is the latest human-reviewed scene evidence export.
- `scene_evidence_current/observation_ledger.jsonl` is the runtime observation ledger.
- `scene_evidence_current/bbox_review_decisions.csv` is the latest accepted bbox decision table.
- `tools/bbox_review_ui/` contains the retained bbox review utility; historical backups are excluded.

Earlier pilot, midrun, preview, detector, aggregation, review, audit, cache, and
figure products were removed on 2026-09-15. Raw camera, lidar, pose, calibration,
and manual source files live outside this workspace and were not modified.
