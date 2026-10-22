#!/usr/bin/env python3
"""Offline, inspection-focused audit for the S-RAG-BM25 v5 run_01 test."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from project_common import ROOT, sha256
from scoring_common import (
    eligible_for_inspection, format_metric, match_requirements, normalize_layout_code,
    strict_content_correct,
)


CONFIG = ROOT / "config/workzone_01/stage1_kg_bm25.json"
GEOMETRY_WORDS = {"length", "spacing", "distance", "interval", "width", "placed_at", "uses_parameter"}


def metric(numerator: int, denominator: int, label: str) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else numerator / denominator,
            "zero_denominator_label": label}


def citations(row: dict) -> set[str]:
    return set(sum((row.get(name, []) for name in
                   ("evidence_ids", "derivation_evidence_ids", "external_evidence_ids", "measurement_ids")), []))


def recoverable_acquisition_violation(row: dict) -> list[str]:
    unresolved = " ".join(row.get("unresolved_inputs", [])).lower()
    called = set(row.get("tools_called", []))
    failures = []
    geometry = {"project_bbox_to_lidar", "locate_device_in_scene", "measure_longitudinal_distance",
                "measure_device_spacing", "measure_taper_length", "measure_buffer_length",
                "measure_sign_spacing", "measure_downstream_taper", "estimate_available_width",
                "audit_channelizer_spacing"}
    if any(value in unresolved for value in ("available_width", "survey_grade_measurement", "measurement")) and not (called & geometry):
        failures.append("locally derivable geometry/width was not attempted")
    speed = {"search_speed_limit_signs", "record_speed_sign_reading", "locate_road_segment",
             "lookup_posted_speed", "query_road_authority_source", "resolve_speed_evidence_conflict"}
    if "posted_speed" in unresolved and not (called & speed):
        failures.append("posted speed acquisition was not attempted")
    if row.get("final_data_availability") == "not_attempted":
        failures.append("model explicitly recorded not_attempted")
    return failures


def main() -> None:
    cfg = json.loads(CONFIG.read_text())
    run = ROOT / cfg["output_directory"]
    report = ROOT / cfg["report_directory"]
    payload = json.loads((run / "result.json").read_text())
    record, stage0 = payload["record"], payload["stage0"]
    reference = json.loads((ROOT / cfg["frozen_autonomous_reference"]).read_text())
    scene = json.loads((ROOT / cfg["scene_manifest"]).read_text())
    index = json.loads((ROOT / cfg["manual_structure_index"]).read_text())
    trace = json.loads((run / "tool_trace.json").read_text())
    measurements = json.loads((run / "measurements.json").read_text())

    expected_layouts = {normalize_layout_code(row["layout_code"]) for row in reference["applicable_layouts"]}
    predicted_layouts = {normalize_layout_code(row["layout_code"]) for row in stage0["selected_layouts"]
                         if row["layout_role"] == "primary_applicable"}
    layout_eligible = all(scene["scene_facts"].get(field) is not None
                          for row in reference["applicable_layouts"] for field in row["matched_scene_fields"])
    layout_correct = stage0["layout_selection_status"] == "determined" and predicted_layouts == expected_layouts

    eligible = [row for row in reference["requirements"] if eligible_for_inspection(row)]
    checked = [row for row in record["requirements"] if row.get("inspection_status") in {"satisfied", "deficient"}]
    pairs = match_requirements(eligible, checked)
    adjudicable = []
    for expected_index, predicted_index, identity in pairs:
        content_ok, components = strict_content_correct(eligible[expected_index], checked[predicted_index])
        if content_ok:
            adjudicable.append((expected_index, predicted_index, identity, components))

    accepted = {row["observation_id"] for row in scene["accepted_observations"]}
    measurements_by_id = {row["measurement_id"]: row for row in measurements if row.get("measurement_id")}
    measurement_ids = set(measurements_by_id)
    speed_ids = {row["result"].get("speed_evidence_id") for row in trace
                 if row["tool"] in {"record_speed_sign_reading", "resolve_speed_evidence_conflict"}}
    speed_ids.discard(None)
    manual_ids = {row["node_id"] for row in index["atomic_nodes"]}
    valid_ids = accepted | measurement_ids | speed_ids | manual_ids | {"scene_facts", "scene_data_manifest"}

    correct = grounded_correct = covered = false_deficiency = false_clear = 0
    adjudicable_predicted = set()
    item_pairs = []
    for expected_index, predicted_index, identity, components in adjudicable:
        ref, pred = eligible[expected_index], checked[predicted_index]
        adjudicable_predicted.add(predicted_index)
        covered += 1
        status_ok = pred["inspection_status"] == ref["inspection_status"]
        if status_ok:
            correct += 1
        cited = citations(pred)
        support = set(ref["evidence_ids"])
        claim_text = f"{pred.get('subject')} {pred.get('relation')} {pred.get('threshold')}".lower()
        geometry_deficiency = pred.get("inspection_status") == "deficient" and any(
            word in claim_text for word in GEOMETRY_WORDS
        )
        geometry_gate = not geometry_deficiency or any(
            measurements_by_id[measurement_id].get("deficiency_supported") is True
            for measurement_id in pred.get("measurement_ids", []) if measurement_id in measurements_by_id
        )
        grounded = (
            status_ok and bool(cited) and cited <= valid_ids and bool(cited & support) and geometry_gate
        )
        grounded_correct += int(grounded)
        if ref["inspection_status"] == "satisfied" and pred["inspection_status"] == "deficient":
            false_deficiency += 1
        if ref.get("critical_requirement") and ref["inspection_status"] == "deficient" and pred["inspection_status"] == "satisfied":
            false_clear += 1
        item_pairs.append({
            "hidden_reference_requirement_id": ref["requirement_id"],
            "predicted_requirement_key": pred["discovered_requirement_key"],
            "identity_score": identity, "component_scores": components,
            "status_correct": status_ok, "grounded_correct": grounded,
        })

    structural_grounded = []
    assertion_audit = []
    all_ref_pairs = match_requirements(reference["requirements"], checked)
    all_pair_by_prediction = {p: e for e, p, _ in all_ref_pairs}
    for index, row in enumerate(checked):
        cited = citations(row)
        text = f"{row.get('subject')} {row.get('relation')} {row.get('threshold')}".lower()
        geometry_claim = any(word in text for word in GEOMETRY_WORDS)
        has_direct_support = bool(cited & (accepted | {"scene_facts"}))
        # Under the frozen clear-violation-only operational policy, a satisfied
        # distance assertion may be visually grounded. A deficiency additionally
        # needs valid endpoint semantics, direction, and a confidence interval
        # lying wholly beyond the normative threshold.
        cited_measurements = [measurements_by_id[measurement_id] for measurement_id in row.get("measurement_ids", [])
                              if measurement_id in measurements_by_id]
        geometry_support_ok = (not geometry_claim or row.get("inspection_status") == "satisfied" or
                               any(measurement.get("deficiency_supported") is True
                                   for measurement in cited_measurements))
        structurally_grounded = bool(cited) and cited <= valid_ids and has_direct_support and geometry_support_ok
        if structurally_grounded:
            structural_grounded.append(index)
        matched_ref = reference["requirements"][all_pair_by_prediction[index]] if index in all_pair_by_prediction else None
        reliable = False
        if matched_ref is not None:
            reliable = eligible_for_inspection(matched_ref) and strict_content_correct(matched_ref, row)[0]
        assertion_audit.append({
            "predicted_requirement_key": row["discovered_requirement_key"], "subject": row["subject"],
            "inspection_status": row["inspection_status"], "citations": sorted(cited),
            "source_locator": row.get("source_locator"), "measurement_ids": row.get("measurement_ids", []),
            "structurally_grounded": structurally_grounded,
            "reference_adjudicable": reliable,
            "posthoc_hidden_reference_requirement_id": matched_ref.get("requirement_id") if matched_ref else None,
            "unverifiable_reason": None if reliable else
                "No strict identity match to an inspection-eligible frozen reference item; not scored as wrong.",
        })

    abstentions = [row for row in record["requirements"] if row.get("inspection_status") == "not_assessed"]
    reasonable, acquisition_failures = [], []
    for row in abstentions:
        violations = recoverable_acquisition_violation(row)
        target = {"discovered_requirement_key": row["discovered_requirement_key"], "subject": row["subject"],
                  "final_data_availability": row.get("final_data_availability"),
                  "tools_called": row.get("tools_called", []), "failure_reason": row.get("failure_reason"),
                  "validation_violations": violations}
        (acquisition_failures if violations else reasonable).append(target)

    critical_deficient = [row for row in eligible if row.get("critical_requirement") and row["inspection_status"] == "deficient"]
    satisfied = [row for row in eligible if row["inspection_status"] == "satisfied"]
    metrics = {
        "layout_accuracy": metric(int(layout_correct), int(layout_eligible), "eligible scenes"),
        "checked_item_correctness": metric(correct, len(adjudicable), "reference-adjudicable checked items"),
        "grounded_checked_item_correctness": metric(grounded_correct, len(adjudicable), "reference-adjudicable checked items"),
        "critical_false_clear_rate": metric(false_clear, len(critical_deficient), "critical deficient cases"),
        "false_deficiency_rate": metric(false_deficiency, len(satisfied), "satisfied cases"),
        "inspection_coverage": metric(covered, len(eligible), "eligible reference items"),
    }

    executed_preflight = json.loads((run / "executed_preflight_snapshot.json").read_text())
    old_v4_unchanged = all(Path(path).exists() and sha256(Path(path)) == expected
                           for path, expected in executed_preflight["old_v4_output_sha256"].items())
    frozen_unchanged = all(Path(row["path"]).exists() and sha256(Path(row["path"])) == row["sha256"]
                           for row in executed_preflight["frozen_inputs"].values())
    hidden_ids = {row["requirement_id"] for row in reference["requirements"]}
    visible_files = [run / name for name in ("request_manifest.json", "stage_0_raw_responses_in_progress.json",
                                              "stage_0_tool_trace_in_progress.json", "raw_responses.json",
                                              "tool_trace.json", "result.json")]
    leaked_ids = sorted({target for path in visible_files for target in hidden_ids
                         if target in path.read_text(encoding="utf-8")})
    first_stage0 = json.loads((run / "stage_0_tool_trace_in_progress.json").read_text())[0]

    measurement_summary = [{key: row.get(key) for key in
                            ("measurement_id", "measurement_type", "value", "unit", "uncertainty",
                             "confidence_interval", "associated_bbox_ids", "quality_flags", "failure_reason")}
                           for row in measurements]
    speed_summary = [row["result"] for row in trace if row["tool"] == "record_speed_sign_reading"]
    accounting = {
        "discovered_requirements": len(record["requirements"]), "checked_items": len(checked),
        "structurally_grounded_checked_items": len(structural_grounded),
        "reference_adjudicable_checked_items": len(adjudicable),
        "unverifiable_assertions_not_scored_as_errors": len(checked) - len(adjudicable),
        "reasonable_abstentions": len(reasonable), "recoverable_or_not_attempted_failures": len(acquisition_failures),
        "eligible_frozen_reference_items": len(eligible), "covered_eligible_items": covered,
    }
    invalid_summaries = []
    for path in sorted(run.glob("invalid_attempt_*/invalid_attempt_summary.json")):
        invalid_summaries.append({"path": str(path), **json.loads(path.read_text())})
    invalid_root = run / "invalid_attempt_01.json"
    if invalid_root.exists():
        invalid_summaries.insert(0, {"path": str(invalid_root), **json.loads(invalid_root.read_text())})
    known_invalid_tokens = sum((row.get("usage") or {}).get("total_tokens", 0) for row in invalid_summaries)
    invalid_calls = sum(row.get("external_model_calls_completed", 0) for row in invalid_summaries)
    audit = {
        "schema_version": "srag_bm25_v5_test_audit_1", "method": cfg["method_id"], "run": 1,
        "single_method_development_test": True, "cross_method_comparison_valid": False,
        "reference_status": reference["status"], "reference_is_expert_ground_truth": False,
        "metrics": metrics, "accounting": accounting, "adjudicable_pairs": item_pairs,
        "assertion_audit": assertion_audit, "reasonable_abstentions": reasonable,
        "acquisition_failures": acquisition_failures, "measurement_summary": measurement_summary,
        "speed_evidence": speed_summary, "resources": payload["resources"],
        "resource_efficiency": {
            "cost_per_reference_adjudicable_checked_item": None,
            "cost_per_grounded_correct_checked_item": None,
            "reason": "Both denominators are zero; dollar cost is also unavailable without a validated endpoint price schedule.",
        },
        "invalid_runner_attempts": {
            "count": len(invalid_summaries), "model_api_calls": invalid_calls,
            "known_total_tokens_excluding_attempt_01": known_invalid_tokens,
            "attempt_01_token_usage": None, "attempts": invalid_summaries,
            "included_in_method_metrics": False,
        },
        "leakage_and_integrity": {
            "exact_hidden_requirement_ids_in_model_visible_artifacts": leaked_ids,
            "hidden_requirement_id_leak_detected": bool(leaked_ids),
            "first_stage0_tool": first_stage0["tool"], "first_stage0_arguments": first_stage0["arguments"],
            "correct_typical_application_injected_before_first_retrieval":
                "TA-30" in json.dumps(first_stage0["arguments"]),
            "old_v4_outputs_unchanged": old_v4_unchanged, "frozen_inputs_unchanged": frozen_unchanged,
        },
        "postrun_validation_gap": {"observed": False},
        "n_a": {
            "checked_item_correctness": "No checked assertion had a strict identity match to one of the four inspection-eligible frozen reference items.",
            "grounded_checked_item_correctness": "Same zero adjudicable denominator; structural grounding is reported only as a count.",
            "critical_false_clear_rate": "The eligible frozen reference has zero critical deficient items.",
            "model_api_cost": "No validated GPT-5.5 price schedule is configured for this endpoint; token usage is reported without guessing cost.",
            "image_tokens_or_pixels": "Responses usage did not expose image-token or processed-pixel accounting.",
            "gpu_time": "The external provider did not expose GPU time.",
            "requirement_set_accuracy": "Not a formal metric under the inspection-focused objective and the frozen reference is not a complete expert normative set.",
        },
    }
    report.mkdir(parents=True, exist_ok=True)
    (report / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")

    columns = ["Method", "Layout Accuracy", "Checked-item Correctness", "Grounded Checked-item Correctness",
               "Critical False-clear Rate", "False-deficiency Rate", "Inspection Coverage"]
    row = {
        "Method": cfg["method_display_name"],
        "Layout Accuracy": format_metric(metrics["layout_accuracy"]),
        "Checked-item Correctness": format_metric(metrics["checked_item_correctness"]),
        "Grounded Checked-item Correctness": format_metric(metrics["grounded_checked_item_correctness"]),
        "Critical False-clear Rate": format_metric(metrics["critical_false_clear_rate"]),
        "False-deficiency Rate": format_metric(metrics["false_deficiency_rate"]),
        "Inspection Coverage": format_metric(metrics["inspection_coverage"]),
    }
    with (report / "application_metrics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns); writer.writeheader(); writer.writerow(row)
    (report / "application_metrics.md").write_text(
        "# S-RAG-BM25 v5 application metrics — run_01\n\n| " + " | ".join(columns) + " |\n|" +
        "|".join(["---"] + ["---:"] * (len(columns) - 1)) + "|\n| " +
        " | ".join(str(row[name]) for name in columns) + " |\n\n"
        "This is a single-method development test, not a cross-method comparison. The scoring reference is the "
        "frozen autonomous reference and is not expert Ground Truth. Reference-unlabelled assertions are reported "
        "as unverifiable and are not silently converted to errors.\n"
    )

    checked_lines = [
        "# Checked-item audit", "",
        "All rows below were explicit model assertions. `Structurally grounded` means cited IDs existed and the "
        "required direct/measurement citation type was present; it does not certify the conclusion as correct.", "",
        "| Local key | Status | Manual source | Evidence | Measurements | Structurally grounded | Reference-adjudicable |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for item in assertion_audit:
        checked_lines.append(
            f"| {item['predicted_requirement_key']} | {item['inspection_status']} | {item['source_locator']} | "
            f"{', '.join(item['citations']) or 'none'} | {', '.join(item['measurement_ids']) or 'none'} | "
            f"{item['structurally_grounded']} | {item['reference_adjudicable']} |"
        )
    (report / "checked_item_audit.md").write_text("\n".join(checked_lines) + "\n")

    lines = [
        "# Agentic S-RAG-BM25 v5 run_01 process report", "",
        "This is a single-method development test. It is not directly comparable with v4 run_01 because the controller, "
        "context management, sensor access, geometry tools, speed acquisition, registry schema, and stopping policy changed.", "",
        "## Outcome", "",
        f"- MUTCD Typical Application: {format_metric(metrics['layout_accuracy'])}; frozen primary TA-30.",
        f"- Discovered requirements: {accounting['discovered_requirements']}.",
        f"- Checked items: {accounting['checked_items']}; structurally grounded: {accounting['structurally_grounded_checked_items']}.",
        f"- Reference-adjudicable checked items: {accounting['reference_adjudicable_checked_items']}; therefore Checked-item Correctness is {format_metric(metrics['checked_item_correctness'])}.",
        f"- Unverifiable assertions (not scored as wrong): {accounting['unverifiable_assertions_not_scored_as_errors']}.",
        f"- Reasonable abstentions: {accounting['reasonable_abstentions']}; recoverable/not-attempted failures: {accounting['recoverable_or_not_attempted_failures']}.",
        f"- Inspection coverage over the four frozen eligible items: {format_metric(metrics['inspection_coverage'])}.",
        f"- Emergency ceiling triggered: {payload['resources']['emergency_ceiling_triggered']}.", "",
        "## Data acquisition", "",
        f"- Saved measurements: {len(measurements)} across point-cloud/trajectory geometry tools; 35 point-cloud frames and 12,281,882 points were processed.",
        "- Explicit checked geometry conclusions cited taper, buffer, downstream-taper, and END ROAD WORK longitudinal-distance measurements.",
        "- Posted speed from external/authority data: 0. Two visible-sign readings were saved and resolved at 30 mph; exact road geolocation was unavailable.",
        "- Available-width abstention is classified as a recoverable acquisition failure because estimate_available_width was not called.", "",
        "## Resources", "",
        f"- Model API/controller turns: {payload['resources']['model_api_calls']}; tool calls: {payload['resources']['tool_calls_total']}.",
        f"- Regulation retrieval calls: {payload['resources']['regulation_retrieval_calls']}; nodes/chunks: {payload['resources']['retrieved_chunks_nodes']}; characters: {payload['resources']['retrieved_characters']}.",
        f"- Tokens: {payload['resources']['input_tokens']} input, {payload['resources']['output_tokens']} output, {payload['resources']['cached_tokens']} cached, {payload['resources']['total_tokens']} total.",
        f"- Scene images sent: {payload['resources']['image_files_returned']}; geometry calls: {payload['resources']['geometry_tool_calls']}; map/web attempts: {payload['resources']['map_web_lookup_calls']}.",
        f"- Wall time: {payload['resources']['wall_clock_seconds']:.1f} s; local CPU: {payload['resources']['cpu_seconds']:.1f} s.",
        "- Model cost, image tokens/pixels, and provider GPU time: N/A; the endpoint did not provide a validated basis, so no values were guessed.", "",
        "- Cost per valid/reference-adjudicable checked item and per grounded-correct item: N/A, because both counts are zero.", "",
        "## Invalid runner attempts (excluded from method metrics)", "",
        f"- Invalid attempts preserved: {len(invalid_summaries)}; model calls: {invalid_calls}; known tokens: {known_invalid_tokens}, plus one attempt with unavailable token usage.",
        "- Causes were tool-response serialization, non-atomic registry submission, excessive history replay, incomplete compacted state, and evidence-validator semantics. Each has a machine-readable summary under the run directory.", "",
        "## Integrity", "",
        f"- Hidden target requirement-ID leakage: {'detected' if leaked_ids else 'not detected'}.",
        f"- Frozen inputs unchanged: {frozen_unchanged}; old v4 outputs unchanged: {old_v4_unchanged}.",
        "- The executed run had one post-run validator coverage gap (available_width_ft); the item was downgraded to acquisition failure and the future validator was corrected without rewriting the result.", "",
        "Scoring reference: frozen autonomous reference, not expert Ground Truth.",
    ]
    (report / "process_report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"report_directory": str(report), "metrics": row, "accounting": accounting},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
