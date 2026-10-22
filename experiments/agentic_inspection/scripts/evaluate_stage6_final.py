#!/usr/bin/env python3
"""Evaluate a finalized Stage 6 registry without using hidden answer data."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


COPY_FIELDS = (
    "normative_applicability", "acquisition_plan", "acquisition_attempts",
    "tools_called", "acquired_inputs", "derivation_evidence_ids",
    "external_evidence_ids", "unresolved_inputs", "final_data_availability",
    "failure_reason", "image_assessable", "inspection_status", "evidence_ids",
    "measurement_ids", "inspection_reason", "requires_human_review",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    record = result["record"]
    resources = result.get("resources", {})
    requirements = {
        row["discovered_requirement_key"]: row
        for row in record.get("requirements", [])
    }
    drafts = record.get("conclusion_drafts", {})
    mismatches = {}
    for key, draft in drafts.items():
        final = requirements.get(key, {})
        different = [field for field in COPY_FIELDS if draft.get(field) != final.get(field)]
        if different:
            mismatches[key] = different

    statuses = Counter(row.get("inspection_status") for row in requirements.values())
    classes = Counter(
        "Mandatory" if row.get("modality") == "shall" else "Guidance"
        for row in requirements.values()
    )
    evaluation = {
        "schema_version": "stage6_final_evaluation_v1",
        "passed": bool(
            result.get("status") == "completed"
            and record.get("phase") == "finalized"
            and record.get("finalized") is True
            and requirements
            and set(requirements) == set(drafts)
            and not mismatches
            and record.get("completion", {}).get("agent_declared_completion_status") == "complete"
            and resources.get("session_tool_failures") == 0
        ),
        "registered_requirement_count": len(requirements),
        "final_result_count": len(requirements),
        "conclusion_draft_count": len(drafts),
        "exact_stage5_copy_count": len(drafts) - len(mismatches),
        "copy_mismatches": mismatches,
        "normative_class_counts": dict(classes),
        "inspection_status_counts": dict(statuses),
        "session_tool_calls": resources.get("session_tool_calls"),
        "session_tool_failures": resources.get("session_tool_failures"),
        "model_api_calls": resources.get("model_api_calls"),
        "total_tokens": resources.get("total_tokens"),
        "wall_clock_seconds": resources.get("wall_clock_seconds"),
        "actual_model_api_cost_usd": resources.get("actual_model_api_cost_usd"),
    }
    output = args.output or args.result.parent / "stage6_final_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))
    if not evaluation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
