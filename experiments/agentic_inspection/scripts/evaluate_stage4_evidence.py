#!/usr/bin/env python3
"""Evaluate the Stage 4 evidence-acquisition boundary without forming conclusions."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


CHANNELIZER_CLASSES = (
    "channelizing_device",
    "traffic_cone",
    "traffic_drum",
    "barricade",
)
STAGE5_TOOLS = {"begin_result_submission", "submit_inspection_batch", "finalize_registry"}


def _evidence_rows(record: dict) -> list[dict]:
    rows = record.get("evidence_records", {})
    return list(rows.values()) if isinstance(rows, dict) else list(rows)


def _measurement_rows(path: Path) -> list[dict]:
    value = json.loads(path.read_text()) if path.exists() else []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    root = args.result.parent
    record = result["record"]
    trace = json.loads((root / "tool_trace.json").read_text())
    measurements = _measurement_rows(root / "measurements.json")
    resources = result.get("resources", {})
    resumed = int(resources.get("resumed_tool_calls", 0))
    stage4_trace = trace[resumed:]

    inventories: dict[str, set[str]] = defaultdict(set)
    inspected_by_class: dict[str, set[str]] = defaultdict(set)
    inspected_observations: set[str] = set()
    inspected_temporal_ids: set[str] = set()
    manifest = {}
    failures = []
    for row in stage4_trace:
        tool = row.get("tool")
        arguments = row.get("arguments", {})
        tool_result = row.get("result", {})
        if tool_result.get("status") == "failure":
            failures.append({
                "step": row.get("step"),
                "tool": tool,
                "failure_reason": tool_result.get("failure_reason"),
            })
        if tool == "get_scene_data_manifest" and not manifest:
            manifest = tool_result
        elif tool == "get_reviewed_observations":
            reviewed_class = arguments.get("reviewed_class")
            inventories[reviewed_class].update(
                item["observation_id"] for item in tool_result.get("observations", [])
            )
        elif tool == "inspect_observation_images" and tool_result.get("status") != "failure":
            for item in tool_result.get("observations", []):
                observation_id = item["observation_id"]
                inspected_observations.add(observation_id)
                inspected_by_class[item.get("reviewed_class")].add(observation_id)
        elif tool == "inspect_temporal_images" and tool_result.get("status") != "failure":
            inspected_temporal_ids.update(
                item["image_id"] for item in tool_result.get("images", [])
            )

    # Orchestrated Stage 4 intentionally hides the underlying raw image tools
    # from the model.  Reconstruct coverage from the frozen plan and persisted
    # bundles rather than treating that abstraction boundary as missing data.
    plan = record.get("stage4_plan") or {}
    bundles_value = record.get("inspection_bundles", {})
    bundles = (list(bundles_value.values()) if isinstance(bundles_value, dict)
               else list(bundles_value))
    if plan and bundles:
        bundle_by_job = {row.get("visual_job_id"): row for row in bundles}
        for job in plan.get("visual_jobs", []):
            bundle = bundle_by_job.get(job.get("visual_job_id"), {})
            source_ids = set(bundle.get("source_ids", []))
            if job.get("job_type") == "temporal_batch":
                inspected_temporal_ids.update(source_ids)
            else:
                inspected_observations.update(source_ids)
            for source_id, metadata in bundle.get("source_metadata", {}).items():
                reviewed_class = metadata.get("reviewed_class")
                if reviewed_class:
                    inspected_by_class[reviewed_class].add(source_id)
                    inventories[reviewed_class].add(source_id)
            if job.get("role") == "traffic_sign_representatives":
                inventories["traffic_sign"].update(job.get("observation_ids", []))
            elif job.get("role") == "device_representatives":
                for reviewed_class in job.get("reviewed_classes", []):
                    if reviewed_class == "arrow_board" and not inventories[reviewed_class]:
                        inventories[reviewed_class].update(
                            source_id for source_id, metadata
                            in bundle.get("source_metadata", {}).items()
                            if metadata.get("reviewed_class") == reviewed_class
                        )

    trajectory = manifest.get("trajectory", {})
    temporal_timestamps = []
    for row in stage4_trace:
        if row.get("tool") == "inspect_temporal_images":
            temporal_timestamps.extend(
                item["timestamp_us"] for item in row.get("result", {}).get("images", [])
                if item.get("timestamp_us") is not None
            )
    traversal_duration = max(
        1,
        int(trajectory.get("end_timestamp_us", 0)) - int(trajectory.get("start_timestamp_us", 0)),
    )
    temporal_span_ratio = (
        (max(temporal_timestamps) - min(temporal_timestamps)) / traversal_duration
        if len(temporal_timestamps) >= 2 else 0.0
    )
    temporal_jobs = [
        row for row in plan.get("visual_jobs", [])
        if row.get("job_type") == "temporal_batch"
    ]
    if temporal_jobs:
        temporal_job = temporal_jobs[0]
        total_frames = max(1, int(temporal_job.get("total_frames", 1)))
        sampled_span = max(0, int(temporal_job.get("count", 0)) - 1) * int(
            temporal_job.get("stride", 1)
        )
        temporal_span_ratio = min(1.0, sampled_span / max(1, total_frames - 1))

    evidence = _evidence_rows(record)
    evidence_by_requirement: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        evidence_by_requirement[row["discovered_requirement_key"]].append(row)

    requirement_rows = []
    for requirement in record.get("requirements", []):
        key = requirement["discovered_requirement_key"]
        rows = evidence_by_requirement.get(key, [])
        acquired = {
            value for row in rows for value in row.get("acquired_inputs", [])
        }
        unresolved = {
            value for row in rows for value in row.get("unresolved_inputs", [])
        }
        required = set(requirement.get("required_inputs", []))
        requirement_rows.append({
            "candidate_label": requirement.get("candidate_label"),
            "discovered_requirement_key": key,
            "region": requirement.get("region"),
            "required_inputs": requirement.get("required_inputs", []),
            "measurement_tool": (requirement.get("measurement_spec") or {}).get("tool"),
            "evidence_record_count": len(rows),
            "evidence_kinds": sorted({row.get("evidence_kind") for row in rows}),
            "required_inputs_accounted": acquired | unresolved == required,
            "acquired_unresolved_overlap": sorted(acquired & unresolved),
            "acquired_inputs": sorted(acquired),
            "unresolved_inputs": sorted(unresolved),
            "source_ids": sorted({
                source for row in rows for source in row.get("source_ids", [])
            }),
        })

    measurement_by_type = {row.get("measurement_type"): row for row in measurements}
    spacing = measurement_by_type.get("channelizer_spacing_series", {})
    taper = measurement_by_type.get("taper_length", {})
    spacing_usable = bool(
        spacing.get("status") == "acquired"
        and spacing.get("sequence_inference_valid") is True
    )
    taper_usable = bool(
        taper.get("status") == "acquired"
        and taper.get("endpoint_semantics_valid") is True
        and taper.get("geometry_direction_valid") is True
        and taper.get("threshold_assessment", {}).get("status") != "geometry_not_eligible"
        and "large_trajectory_lateral_residual" not in taper.get("quality_flags", [])
    )
    taper_rows = [
        row for row in requirement_rows
        if row.get("measurement_tool") == "measure_taper_length"
    ]
    invalid_taper_remained_unresolved = bool(
        not taper_usable and taper_rows
        and all(row.get("unresolved_inputs") for row in taper_rows)
    )
    planned_present_classes = {
        reviewed_class
        for job in plan.get("visual_jobs", [])
        if job.get("role") == "device_representatives"
        for reviewed_class in job.get("reviewed_classes", [])
    }
    present_channelizer_classes = sorted(
        reviewed_class for reviewed_class in CHANNELIZER_CLASSES
        if (reviewed_class in planned_present_classes or
            manifest.get("counts", {}).get(
                "accepted_bbox_observations_by_class", {}
            ).get(reviewed_class, 0))
    )

    conclusion_leakage = []
    for row in evidence:
        text = f"{row.get('finding', '')} {row.get('limitations', '')}".casefold()
        leaked = [term for term in ("requirement satisfied", "requirement deficient") if term in text]
        if leaked:
            conclusion_leakage.append({
                "evidence_id": row.get("evidence_id"),
                "terms": leaked,
            })

    sign_inventory = inventories.get("traffic_sign", set())
    arrow_inventory = inventories.get("arrow_board", set())
    coverage = {
        "traffic_sign_representatives_inventoried": len(sign_inventory),
        "traffic_sign_representatives_inspected": len(sign_inventory & inspected_observations),
        "all_inventoried_traffic_signs_inspected": bool(sign_inventory) and sign_inventory <= inspected_observations,
        "arrow_board_representatives_inventoried": len(arrow_inventory),
        "arrow_board_representatives_inspected": len(arrow_inventory & inspected_observations),
        "all_inventoried_arrow_boards_inspected": bool(arrow_inventory) and arrow_inventory <= inspected_observations,
        "present_channelizer_classes": present_channelizer_classes,
        "inspected_channelizer_classes": sorted(
            reviewed_class for reviewed_class in present_channelizer_classes
            if inspected_by_class.get(reviewed_class)
        ),
        "all_present_channelizer_classes_sampled": all(
            inspected_by_class.get(reviewed_class) for reviewed_class in present_channelizer_classes
        ),
        "cam_front_temporal_frame_count": len(inspected_temporal_ids),
        "cam_front_temporal_span_ratio": temporal_span_ratio,
        "temporal_coverage_passed": len(inspected_temporal_ids) >= 8 and temporal_span_ratio >= 0.70,
    }

    evidence_structure_passed = bool(
        requirement_rows
        and all(row["evidence_record_count"] >= 1 for row in requirement_rows)
        and all(row["required_inputs_accounted"] for row in requirement_rows)
        and not any(row["acquired_unresolved_overlap"] for row in requirement_rows)
        and not conclusion_leakage
    )
    coverage_passed = bool(
        coverage["all_inventoried_traffic_signs_inspected"]
        and coverage["all_inventoried_arrow_boards_inspected"]
        and coverage["all_present_channelizer_classes_sampled"]
        and coverage["temporal_coverage_passed"]
    )
    boundary_passed = bool(
        result.get("status") == "awaiting_stage4_evaluation"
        and result.get("stopped_after_measurements") is True
        and record.get("phase") == "inspection_conclusion"
        and not record.get("finalized")
        and not any(row.get("tool") in STAGE5_TOOLS for row in stage4_trace)
    )
    measurement_quality_passed = bool(spacing_usable and invalid_taper_remained_unresolved)
    structural_passed = bool(
        evidence_structure_passed and coverage_passed and boundary_passed and measurement_quality_passed
    )
    traceability_warnings = []
    channelizer_visual_rows = [
        row for row in requirement_rows
        if row.get("region") == "channelization_system"
        and any(value in {"raw_images", "accepted_bbox_observations", "channelization_region"}
                or "observ" in value.casefold() or "image" in value.casefold()
                for value in row.get("required_inputs", []))
    ]
    for row in channelizer_visual_rows:
        row_evidence = evidence_by_requirement.get(
            row["discovered_requirement_key"], []
        )
        has_binding_confirmed_deficiency = any(
            evidence_row.get("evidence_kind") == "direct_fact"
            and evidence_row.get("finding", "").startswith(
                "User/domain-reviewer confirmed device-condition findings:"
            )
            for evidence_row in row_evidence
        )
        if has_binding_confirmed_deficiency:
            continue
        sources = set(row.get("source_ids", []))
        bound_classes = {
            reviewed_class for reviewed_class in CHANNELIZER_CLASSES
            if inspected_by_class.get(reviewed_class, set()) & sources
        }
        if bound_classes != set(present_channelizer_classes):
            traceability_warnings.append(
                f"{row['discovered_requirement_key']} does not bind a source from every sampled channelizer class."
            )
    temporal_bound_count = sum(
        bool(set(row.get("source_ids", [])) & inspected_temporal_ids) for row in evidence
    )
    if inspected_temporal_ids and temporal_bound_count == 0:
        traceability_warnings.append(
            "Temporal coverage was inspected, but no accepted evidence record cites a temporal image ID."
        )

    evaluation = {
        "schema_version": "stage4_evidence_evaluation_v2",
        "structural_passed": structural_passed,
        "stable_execution_passed": len(failures) == 0,
        "full_traceability_passed": not traceability_warnings,
        "ready_for_stage5_with_caveats": structural_passed,
        "status": result.get("status"),
        "phase": record.get("phase"),
        "registered_requirement_count": len(requirement_rows),
        "evidence_record_count": len(evidence),
        "requirements_with_evidence": sum(
            row["evidence_record_count"] >= 1 for row in requirement_rows
        ),
        "requirements_with_exact_input_accounting": sum(
            row["required_inputs_accounted"] and not row["acquired_unresolved_overlap"]
            for row in requirement_rows
        ),
        "evidence_kind_counts": dict(Counter(row.get("evidence_kind") for row in evidence)),
        "coverage": coverage,
        "measurements": {
            "saved_count": len(measurements),
            "channelizer_spacing_usable": spacing_usable,
            "channelizer_gaps_evaluated": spacing.get("gaps_evaluated"),
            "channelizer_clear_exceedance_count": spacing.get("clear_exceedance_gap_count"),
            "channelizer_violation_run_count": spacing.get("violation_run_count"),
            "channelizer_deficiency_supported": spacing.get("deficiency_supported"),
            "taper_value_m": taper.get("value"),
            "taper_geometry_usable": taper_usable,
            "taper_threshold_status": taper.get("threshold_assessment", {}).get("status"),
            "invalid_taper_remained_unresolved": invalid_taper_remained_unresolved,
        },
        "stage_boundary_passed": boundary_passed,
        "conclusion_leakage": conclusion_leakage,
        "session_tool_calls": resources.get("session_tool_calls"),
        "session_tool_failures": resources.get("session_tool_failures"),
        "model_api_calls": resources.get("model_api_calls"),
        "total_tokens": resources.get("total_tokens"),
        "wall_clock_seconds": resources.get("wall_clock_seconds"),
        "failed_calls": failures,
        "traceability": {
            "channelizer_visual_requirement_count": len(channelizer_visual_rows),
            "temporal_evidence_record_count": temporal_bound_count,
            "warnings": traceability_warnings,
        },
        "requirements": requirement_rows,
    }
    output = args.output or root / "stage4_evidence_evaluation.json"
    output.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "structural_passed": evaluation["structural_passed"],
        "stable_execution_passed": evaluation["stable_execution_passed"],
        "full_traceability_passed": evaluation["full_traceability_passed"],
        "ready_for_stage5_with_caveats": evaluation["ready_for_stage5_with_caveats"],
        "registered_requirement_count": evaluation["registered_requirement_count"],
        "evidence_record_count": evaluation["evidence_record_count"],
        "coverage": evaluation["coverage"],
        "measurements": evaluation["measurements"],
        "session_tool_calls": evaluation["session_tool_calls"],
        "session_tool_failures": evaluation["session_tool_failures"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
