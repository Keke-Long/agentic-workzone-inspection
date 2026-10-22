#!/usr/bin/env python3
"""Validate the frozen Stage 1–2 method matrix and file identities."""

from __future__ import annotations

import json
from pathlib import Path

from project_common import ROOT, sha256


MANIFEST = ROOT / "config/stage1_stage2_method_manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    failures: list[str] = []
    if manifest.get("status") != "frozen_for_current_study":
        failures.append("manifest status is not frozen_for_current_study")
    if manifest.get("stage2_policy", {}).get("canonical_for_kg_methods") != (
            "structured_candidate_decision_v1"):
        failures.append("canonical KG Stage 2 policy is not structured_candidate_decision_v1")

    definition = manifest["method_definition"]
    definition_path = ROOT / definition["path"]
    if not definition_path.is_file() or sha256(definition_path) != definition["sha256"]:
        failures.append(f"method definition hash mismatch: {definition['path']}")

    for method in manifest.get("methods", []):
        path = ROOT / method["config"]
        if not path.is_file() or sha256(path) != method["config_sha256"]:
            failures.append(f"config hash mismatch: {method['config']}")
            continue
        config = json.loads(path.read_text())
        if config.get("method_id") != method["method_id"]:
            failures.append(f"method_id mismatch: {method['config']}")
        if config.get("method_role") != method["role"]:
            failures.append(f"method role mismatch: {method['config']}")
        if config.get("stage2_policy", {}).get("mode") != method["stage2_mode"]:
            failures.append(f"Stage 2 mode mismatch: {method['config']}")

    for item in manifest.get("frozen_files", []):
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            failures.append(f"frozen file hash mismatch: {item['path']}")

    result = {
        "passed": not failures,
        "manifest": str(MANIFEST),
        "method_count": len(manifest.get("methods", [])),
        "frozen_file_count": len(manifest.get("frozen_files", [])),
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
