#!/usr/bin/env python3
"""Evaluate the isolated Stage 5 conclusion boundary without running Stage 6."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


STAGE6_TOOLS = {
    "submit_inspection_batch", "finalize_registry",
    "submit_next_stage6_batch", "finalize_stage6",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    root = args.result.parent
    record = result["record"]
    resources = result.get("resources", {})
    trace = json.loads((root / "tool_trace.json").read_text())
    stage5_trace = trace[int(resources.get("resumed_tool_calls", 0)):]
    requirements = {
        row["discovered_requirement_key"]: row
        for row in record.get("requirements", [])
    }
    evidence = record.get("evidence_records", {})
    measurements = record.get("measurement_records", {})
    drafts = record.get("conclusion_drafts", {})

    errors: list[str] = []
    rows = []
    for key, requirement in requirements.items():
        draft = drafts.get(key)
        if draft is None:
            errors.append(f"{key}:missing_draft")
            continue
        expected_class = "Mandatory" if requirement.get("modality") == "shall" else "Guidance"
        if draft.get("modality") != requirement.get("modality"):
            errors.append(f"{key}:modality_mismatch")
        if draft.get("normative_class") != expected_class:
            errors.append(f"{key}:normative_class_mismatch")
        if draft.get("requires_human_review") is not False:
            errors.append(f"{key}:human_review_not_false")
        if draft.get("unresolved_inputs") and draft.get("inspection_status") != "not_assessed":
            errors.append(f"{key}:unresolved_but_concluded")
        if (draft.get("normative_applicability") in {"false", "indeterminate"} and
                draft.get("inspection_status") != "not_assessed"):
            errors.append(f"{key}:applicability_but_concluded")
        expected_evidence = {
            evidence_id for evidence_id, evidence_row in evidence.items()
            if evidence_row.get("discovered_requirement_key") == key
        }
        if set(draft.get("evidence_ids", [])) != expected_evidence:
            errors.append(f"{key}:evidence_binding_not_exact")
        if not set(draft.get("measurement_ids", [])).issubset(measurements):
            errors.append(f"{key}:unknown_measurement")
        rows.append({
            "candidate_label": requirement.get("candidate_label"),
            "discovered_requirement_key": key,
            "normative_class": expected_class,
            "normative_applicability": draft.get("normative_applicability"),
            "inspection_status": draft.get("inspection_status"),
            "unresolved_inputs": draft.get("unresolved_inputs", []),
            "evidence_count": len(draft.get("evidence_ids", [])),
            "measurement_count": len(draft.get("measurement_ids", [])),
            "inspection_reason": draft.get("inspection_reason"),
        })

    if set(drafts) - set(requirements):
        errors.append("unexpected_conclusion_keys")
    failures = [
        {"tool": row.get("tool"), "reason": row.get("result", {}).get("failure_reason")}
        for row in stage5_trace if row.get("result", {}).get("status") == "failure"
    ]
    stage6_leakage = [
        row.get("tool") for row in stage5_trace if row.get("tool") in STAGE6_TOOLS
    ]
    readiness = record.get("stage5_readiness") or {}
    boundary_passed = bool(
        result.get("status") == "awaiting_stage5_evaluation"
        and result.get("stopped_after_conclusions") is True
        and record.get("phase") == "result_submission"
        and not record.get("finalized")
        and not stage6_leakage
    )
    status_counts = Counter(row["inspection_status"] for row in rows)
    class_counts = Counter(row["normative_class"] for row in rows)
    status_by_class: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        status_by_class[row["normative_class"]][row["inspection_status"]] += 1

    evaluation = {
        "schema_version": "stage5_conclusion_evaluation_v1",
        "structural_passed": bool(
            bool(requirements) and len(drafts) == len(requirements)
            and not errors
            and readiness.get("ready") is True
        ),
        "stable_execution_passed": not failures,
        "stage_boundary_passed": boundary_passed,
        "ready_for_stage6": bool(not errors and readiness.get("ready") and boundary_passed),
        "registered_requirement_count": len(requirements),
        "conclusion_draft_count": len(drafts),
        "normative_class_counts": dict(class_counts),
        "inspection_status_counts": dict(status_counts),
        "status_by_normative_class": {
            key: dict(value) for key, value in status_by_class.items()
        },
        "checked_count": status_counts["satisfied"] + status_counts["deficient"],
        "reported_deficiency_count": status_counts["deficient"],
        "not_assessed_count": status_counts["not_assessed"],
        "constraint_errors": errors,
        "failed_calls": failures,
        "stage6_leakage": stage6_leakage,
        "session_tool_calls": resources.get("session_tool_calls"),
        "session_tool_failures": resources.get("session_tool_failures"),
        "model_api_calls": resources.get("model_api_calls"),
        "total_tokens": resources.get("total_tokens"),
        "wall_clock_seconds": resources.get("wall_clock_seconds"),
        "actual_model_api_cost_usd": resources.get("actual_model_api_cost_usd"),
        "conclusions": rows,
    }
    output = args.output or root / "stage5_conclusion_evaluation.json"
    output.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        key: evaluation[key] for key in (
            "structural_passed", "stable_execution_passed", "stage_boundary_passed",
            "ready_for_stage6", "registered_requirement_count", "conclusion_draft_count",
            "normative_class_counts", "inspection_status_counts", "session_tool_calls",
            "session_tool_failures",
        )
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
