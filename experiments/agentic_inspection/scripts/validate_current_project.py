#!/usr/bin/env python3
"""Validate the canonical Work Zone 01 handoff package."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from project_common import ROOT


SCENE = ROOT / "cases/workzone_01/scene.json"
FINAL_RESULT = ROOT / "artifacts/workzone_01/pipeline/final_evaluated/scene-CATS-01/result.json"
FINAL_REPORTS = [
    ROOT / "reports/workzone_01/final/stage6_final_report.md",
    ROOT / "reports/workzone_01/final/stage6_final_report.html",
    ROOT / "reports/workzone_01/final/stage6_final_report.pdf",
]
CONFIGS = [
    ROOT / "config/workzone_01/stage1_kg_bm25.json",
    ROOT / "config/workzone_01/stage1_kg_dense.json",
    ROOT / "config/workzone_01/stage1_kg_only.json",
    ROOT / "config/workzone_01/stage1_bm25_only.json",
    ROOT / "config/workzone_01/stage1_dense_only.json",
    ROOT / "config/workzone_01/stage3.json",
    ROOT / "config/workzone_01/stage4.json",
    ROOT / "config/workzone_01/stage5.json",
    ROOT / "config/workzone_01/stage6.json",
]


def main() -> None:
    errors: list[str] = []
    required = [SCENE, FINAL_RESULT, *FINAL_REPORTS, *CONFIGS]
    for path in required:
        if not path.is_file():
            errors.append(f"missing canonical file: {path.relative_to(ROOT)}")

    if errors:
        print(json.dumps({"passed": False, "errors": errors}, indent=2))
        raise SystemExit(1)

    scene = json.loads(SCENE.read_text())
    if scene.get("schema") != "current_scene_v1":
        errors.append("scene schema must be current_scene_v1")
    if scene.get("scene_id") != "scene-CATS-01":
        errors.append("canonical scene_id must be scene-CATS-01")

    expected_findings = {
        "F0622_CAM_BACK_LEFT_000": "I4844",
        "F0616_CAM_FRONT_LEFT_000": "I5502",
    }
    findings = {
        row.get("observation_id"): row.get("element_id")
        for row in scene.get("confirmed_device_condition_findings", [])
    }
    if findings != expected_findings:
        errors.append("the two confirmed channelizer-condition findings changed")

    result = json.loads(FINAL_RESULT.read_text())
    rows = result.get("record", {}).get("requirements", [])
    counts = Counter(row.get("inspection_status") for row in rows)
    expected_counts = {"satisfied": 16, "deficient": 2, "not_assessed": 1}
    if len(rows) != 19 or dict(counts) != expected_counts:
        errors.append(f"final status distribution changed: {dict(counts)}")
    deficient = {
        row.get("candidate_label") for row in rows
        if row.get("inspection_status") == "deficient"
    }
    expected_deficient = {
        "SEC-6K.01 14: Particular attention",
        "SEC-6K.01 15: Channelizing devices that are no longer serviceable (see definition in Section 1C.02)",
    }
    if deficient != expected_deficient:
        errors.append("final deficient requirement set changed")

    for path in CONFIGS:
        config = json.loads(path.read_text())
        scene_path = ROOT / config["scene_manifest"]
        if scene_path != SCENE:
            errors.append(f"{path.name} does not use the canonical scene")

    output = {
        "passed": not errors,
        "errors": errors,
        "scene_id": scene.get("scene_id"),
        "accepted_observations": len(scene.get("accepted_observations", [])),
        "requirements": len(rows),
        "status_counts": dict(counts),
        "configs": len(CONFIGS),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
