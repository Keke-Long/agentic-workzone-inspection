#!/usr/bin/env python3
"""Evaluate a Stage 3 availability-planning checkpoint without using hidden MUTCD answers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inspection_registry_v5 import NORMATIVE_MEASUREMENT_TOOLS, acquisition_tools_for_input


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    record = result["record"]
    requirements = record.get("requirements", [])
    rows = []
    for requirement in requirements:
        availability = requirement.get("data_availability_record") or {}
        required = set(requirement.get("required_inputs", []))
        available = set(availability.get("available_inputs", []))
        missing = set(availability.get("missing_inputs", []))
        state = availability.get("data_availability")
        planned = set(availability.get("planned_tools", []))
        uncovered = {
            input_name: sorted(acquisition_tools_for_input(input_name))
            for input_name in missing
            if acquisition_tools_for_input(input_name)
            and not (acquisition_tools_for_input(input_name) & planned)
        }
        measurement_tool = (requirement.get("measurement_spec") or {}).get("tool")
        semantic_overclaims = sorted(
            input_name for input_name in available
            if input_name.casefold().startswith(("observed ", "measured "))
        )
        state_consistent = (
            (state in {"available_direct", "acquired"} and not missing)
            or (state == "partial" and bool(available) and bool(missing))
            or (state == "not_attempted" and not available and bool(missing))
        )
        rows.append({
            "discovered_requirement_key": requirement.get("discovered_requirement_key"),
            "candidate_label": requirement.get("candidate_label"),
            "condition_data_complete": availability.get("condition_data_complete"),
            "data_availability": state,
            "exact_required_input_partition": not (available & missing) and available | missing == required,
            "availability_state_consistent": state_consistent,
            "semantic_observation_or_measurement_overclaims": semantic_overclaims,
            "uncovered_missing_input_tool_families": uncovered,
            "registered_measurement_tool_planned": not measurement_tool or measurement_tool in planned,
            "has_evidence_strategy": bool(availability.get("planned_evidence_strategy", "").strip()),
            "has_decision_rule": bool(availability.get("planned_decision_rule", "").strip()),
            "has_basis_evidence": bool(availability.get("basis_evidence_ids")),
        })

    resources = result.get("resources", {})
    trace_path = args.result.parent / "tool_trace.json"
    trace = json.loads(trace_path.read_text()) if trace_path.exists() else []
    resumed = int(resources.get("resumed_tool_calls", 0))
    session_trace = trace[resumed:]
    premature_measurements = [
        row.get("tool") for row in session_trace
        if row.get("tool") in NORMATIVE_MEASUREMENT_TOOLS
    ]
    structural_pass = all(
        row["exact_required_input_partition"]
        and row["availability_state_consistent"]
        and not row["semantic_observation_or_measurement_overclaims"]
        and not row["uncovered_missing_input_tool_families"]
        and row["registered_measurement_tool_planned"]
        and row["has_evidence_strategy"]
        and row["has_decision_rule"]
        and row["has_basis_evidence"]
        for row in rows
    )
    evaluation = {
        "schema_version": "stage3_availability_evaluation_v1",
        "passed": (
            structural_pass
            and bool(rows)
            and len(record.get("data_availability", {})) == len(rows)
            and record.get("phase") == "measurement"
            and record.get("review_checkpoint", {}).get("stopped_before_measurement") is True
            and not premature_measurements
        ),
        "registered_requirement_count": len(rows),
        "availability_record_count": len(record.get("data_availability", {})),
        "exact_partition_count": sum(row["exact_required_input_partition"] for row in rows),
        "consistent_state_count": sum(row["availability_state_consistent"] for row in rows),
        "tool_complete_plan_count": sum(
            not row["uncovered_missing_input_tool_families"]
            and row["registered_measurement_tool_planned"] for row in rows
        ),
        "strategy_and_rule_complete_count": sum(
            row["has_evidence_strategy"] and row["has_decision_rule"] for row in rows
        ),
        "semantic_acquisition_boundary_violation_count": sum(
            bool(row["semantic_observation_or_measurement_overclaims"]) for row in rows
        ),
        "condition_data_complete_true_count": sum(
            row["condition_data_complete"] is True for row in rows
        ),
        "condition_data_complete_false_count": sum(
            row["condition_data_complete"] is False for row in rows
        ),
        "premature_normative_measurement_tools": premature_measurements,
        "session_tool_calls": resources.get("session_tool_calls"),
        "session_tool_failures": resources.get("session_tool_failures"),
        "rows": rows,
    }
    output = args.output or args.result.parent / "stage3_availability_evaluation.json"
    output.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: evaluation[key] for key in (
        "passed", "registered_requirement_count", "availability_record_count",
        "exact_partition_count", "consistent_state_count", "tool_complete_plan_count",
        "strategy_and_rule_complete_count", "semantic_acquisition_boundary_violation_count",
        "premature_normative_measurement_tools", "session_tool_calls", "session_tool_failures",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
