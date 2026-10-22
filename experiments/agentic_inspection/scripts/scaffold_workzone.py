#!/usr/bin/env python3
"""Create an isolated case/config skeleton for a new work-zone scene."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from project_common import ROOT


TEMPLATE_ID = "workzone_01"
TEMPLATE_SCENE_ID = "scene-CATS-01"
CONFIG_NAMES = (
    "stage1_kg_bm25.json",
    "stage1_kg_dense.json",
    "stage1_kg_only.json",
    "stage1_bm25_only.json",
    "stage1_dense_only.json",
    "stage3.json",
    "stage4.json",
    "stage5.json",
    "stage6.json",
)


def replace_strings(value: Any, old_workzone: str, new_workzone: str,
                    old_scene: str, new_scene: str) -> Any:
    if isinstance(value, str):
        return value.replace(old_workzone, new_workzone).replace(old_scene, new_scene)
    if isinstance(value, list):
        return [replace_strings(row, old_workzone, new_workzone, old_scene, new_scene)
                for row in value]
    if isinstance(value, dict):
        return {
            key: replace_strings(row, old_workzone, new_workzone, old_scene, new_scene)
            for key, row in value.items()
        }
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workzone-id", required=True,
                        help="Case directory name, for example workzone_02")
    parser.add_argument("--scene-manifest", required=True, type=Path,
                        help="Materialized current_scene_v1 JSON for the new scene")
    args = parser.parse_args()

    workzone_id = args.workzone_id.strip()
    if not re.fullmatch(r"workzone_[0-9]{2,}", workzone_id):
        raise SystemExit("--workzone-id must match workzone_02, workzone_03, ...")
    if workzone_id == TEMPLATE_ID:
        raise SystemExit(f"{TEMPLATE_ID} is the preserved reference case")

    source_scene_path = args.scene_manifest.resolve()
    source_scene = json.loads(source_scene_path.read_text())
    if source_scene.get("schema") != "current_scene_v1":
        raise SystemExit("scene manifest schema must be current_scene_v1")
    scene_id = source_scene.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id:
        raise SystemExit("scene manifest must contain a non-empty scene_id")
    if not isinstance(source_scene.get("accepted_observations"), list):
        raise SystemExit("scene manifest must contain accepted_observations")

    case_dir = ROOT / "cases" / workzone_id
    config_dir = ROOT / "config" / workzone_id
    truth_dir = ROOT / "ground_truth" / workzone_id
    destinations = [case_dir, config_dir, truth_dir]
    existing = [str(path.relative_to(ROOT)) for path in destinations if path.exists()]
    if existing:
        raise SystemExit("refusing to overwrite existing paths: " + ", ".join(existing))

    case_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    truth_dir.mkdir(parents=True)
    (case_dir / "scene.json").write_text(
        json.dumps(source_scene, ensure_ascii=False, indent=2) + "\n"
    )

    template_dir = ROOT / "config" / TEMPLATE_ID
    for name in CONFIG_NAMES:
        config = json.loads((template_dir / name).read_text())
        config = replace_strings(
            config, TEMPLATE_ID, workzone_id, TEMPLATE_SCENE_ID, scene_id
        )
        config["scene_manifest"] = f"cases/{workzone_id}/scene.json"
        config["public_scene_manifest"] = f"cases/{workzone_id}/scene.json"
        config["frozen_autonomous_reference"] = (
            f"ground_truth/{workzone_id}/active_requirements.json"
        )
        if name.startswith("stage1_"):
            execution = config.setdefault("execution", {})
            execution["resume_stage0_record"] = None
            execution["resume_registry_checkpoint"] = None
            execution["resume_tool_trace"] = None
        (config_dir / name).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        )

    (truth_dir / "active_requirements.json").write_text(json.dumps({
        "schema": "pending_manual_reference_v1",
        "workzone_id": workzone_id,
        "scene_id": scene_id,
        "status": "pending_manual_MUTCD_audit",
        "requirements": [],
        "warning": (
            "Do not score retrieval until an independent manual audit replaces "
            "this placeholder. Never expose this file to the inspecting agent."
        ),
    }, ensure_ascii=False, indent=2) + "\n")
    (truth_dir / "README.md").write_text(
        f"# {workzone_id} reference\n\n"
        "Replace `active_requirements.json` only after an independent MUTCD audit. "
        "Keep the reference outside all model prompts and tool responses.\n"
    )

    print(json.dumps({
        "workzone_id": workzone_id,
        "scene_id": scene_id,
        "scene": str((case_dir / "scene.json").relative_to(ROOT)),
        "configs": [str((config_dir / name).relative_to(ROOT)) for name in CONFIG_NAMES],
        "next_steps": [
            "complete the independent active-requirement reference",
            "run preflight for the selected Stage 1 method",
            "run Stage 0-2, then Stage 3, Stage 4, Stage 5, and Stage 6 in order",
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
