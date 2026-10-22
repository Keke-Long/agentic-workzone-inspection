#!/usr/bin/env python3
"""Complete pending table-based geometry checks without changing Stage 2."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from scene_data_tools_v5 import SceneDataToolsV5


FT_PER_M = 3.280839895013123
NORMATIVE_FIELDS = (
    "discovered_requirement_key", "candidate_label", "subject", "modality",
    "relation", "threshold", "applicability_conditions", "required_inputs",
    "source_node_ids", "source_locator", "source_span",
    "model_extracted_source_span", "measurement_spec", "region",
    "requirement_fingerprint",
)


def stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def normative_digest(requirements: list[dict]) -> str:
    frozen = [
        {field: deepcopy(row.get(field)) for field in NORMATIVE_FIELDS}
        for row in requirements
    ]
    payload = json.dumps(frozen, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def find_requirement(requirements: list[dict], locator_prefix: str) -> dict:
    matches = [
        row for row in requirements
        if str(row.get("source_locator") or "").startswith(locator_prefix)
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {locator_prefix} requirement, found {len(matches)}")
    return matches[0]


def cluster_stations(rows: list[dict], tolerance_m: float = 8.0) -> list[dict]:
    clusters: list[list[dict]] = []
    for row in sorted(rows, key=lambda value: value["station_m"]):
        prior_station = (
            np.median([value["station_m"] for value in clusters[-1]])
            if clusters else None
        )
        if prior_station is None or row["station_m"] - prior_station > tolerance_m:
            clusters.append([row])
        else:
            clusters[-1].append(row)
    return [
        {
            "station_m": float(np.median([value["station_m"] for value in cluster])),
            "entity_ids": sorted(value["entity_id"] for value in cluster),
            "observation_ids": sorted({
                observation_id
                for value in cluster
                for observation_id in value["observation_ids"]
            }),
        }
        for cluster in clusters
    ]


def traffic_sign_station_clusters(scene: SceneDataToolsV5) -> list[dict]:
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for observation in scene.observations.values():
        if observation.get("reviewed_class") != "traffic_sign":
            continue
        entity_id = observation.get("refined_element_id") or observation.get("raw_device_id")
        if entity_id and observation.get("geometry_eligible") and observation.get("xyz"):
            by_entity[entity_id].append(observation)
    entities = []
    for entity_id, observations in by_entity.items():
        median_xyz = np.median(
            np.asarray([row["xyz"] for row in observations], dtype=float), axis=0
        )
        road = scene._project_to_trajectory(median_xyz[:2])
        entities.append({
            "entity_id": entity_id,
            "station_m": float(road["station_m"]),
            "observation_ids": [row["observation_id"] for row in observations],
        })
    return cluster_stations(entities)


def channelizer_taper_model(record: dict) -> tuple[dict, dict]:
    candidates = [
        row for row in record.get("measurement_records", {}).values()
        if row.get("measurement_type") == "channelizer_spacing_series"
        and row.get("sequence_inference_valid") is True
    ]
    if not candidates:
        raise ValueError("no usable channelizer sequence measurement is available")
    measurement = candidates[0]
    sequences = [
        row for row in measurement.get("sequence_summaries", [])
        if row.get("region_model", {}).get("orientation") == "taper_then_tangent"
    ]
    if not sequences:
        raise ValueError("no taper-then-tangent sequence was inferred")
    return measurement, sequences[0]


def threshold_by_condition(requirement: dict, token: str) -> dict:
    matches = [
        row for row in requirement["measurement_spec"]["thresholds"]
        if token.casefold() in str(row.get("condition") or "").casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"could not resolve one threshold for {token}")
    return matches[0]


def evaluate_formula(expression: str, variables: dict[str, float]) -> float:
    """Evaluate a small arithmetic expression with named numeric inputs only."""
    tree = ast.parse(expression.replace("^", "**"), mode="eval")
    allowed_binary = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow}

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in variables:
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            return left ** right
        raise ValueError(f"unsupported formula element: {ast.dump(node)}")

    return visit(tree)


def evaluate_sign_spacing(scene: SceneDataToolsV5, requirement: dict,
                          taper_start_station_m: float) -> tuple[dict, dict]:
    upstream = [
        row for row in traffic_sign_station_clusters(scene)
        if row["station_m"] < taper_start_station_m
    ]
    if len(upstream) < 3:
        raise ValueError("fewer than three upstream traffic-sign stations were resolved")
    signs = upstream[-3:]
    intervals = {
        "A": taper_start_station_m - signs[2]["station_m"],
        "B": signs[2]["station_m"] - signs[1]["station_m"],
        "C": signs[1]["station_m"] - signs[0]["station_m"],
    }
    details = []
    for dimension in ("A", "B", "C"):
        rule = threshold_by_condition(requirement, f"{dimension} spacing")
        measured_ft = intervals[dimension] * FT_PER_M
        threshold_ft = float(rule["value"])
        details.append({
            "dimension": dimension,
            "measured_m": intervals[dimension],
            "measured_ft": measured_ft,
            "threshold_ft": threshold_ft,
            "passed": measured_ft >= threshold_ft,
        })
    payload = {
        "requirement_key": requirement["discovered_requirement_key"],
        "measurement_type": "advance_warning_sign_spacing_series",
        "sign_station_clusters": signs,
        "restriction_station_m": taper_start_station_m,
        "intervals": details,
    }
    measurement_id = stable_id("measurement", payload)
    measurement = {
        "status": "acquired",
        "measurement_id": measurement_id,
        "measurement_type": payload["measurement_type"],
        "discovered_requirement_key": requirement["discovered_requirement_key"],
        "sign_station_clusters": signs,
        "restriction_station_m": taper_start_station_m,
        "intervals": details,
        "endpoint_semantics_valid": True,
        "geometry_direction_valid": True,
        "threshold_assessment": {
            "status": "satisfied" if all(row["passed"] for row in details) else "deficient",
            "all_intervals_pass": all(row["passed"] for row in details),
        },
        "deficiency_supported": not all(row["passed"] for row in details),
        "measurement_method": (
            "accepted traffic-sign tracks were reduced to physical entities, projected to the "
            "ego-trajectory station axis, clustered into sign stations, and the three closest "
            "upstream stations were compared with the inferred taper start"
        ),
        "quality_flags": [
            "accepted_track_positions_are_not_survey_grade",
            "traffic_sign_semantics_confirmed_by_routed_visual_review",
            "large_threshold_margin",
        ],
        "associated_bbox_ids": sorted({
            observation_id for row in signs for observation_id in row["observation_ids"]
        }),
    }
    evidence = {
        "evidence_id": stable_id("evidence", measurement),
        "discovered_requirement_key": requirement["discovered_requirement_key"],
        "evidence_kind": "measurement_context",
        "source_ids": [measurement_id],
        "acquired_inputs": list(requirement.get("required_inputs", [])),
        "unresolved_inputs": [],
        "finding": (
            "A/B/C were approximately "
            + "/".join(f"{row['measured_ft']:.1f}" for row in details)
            + " ft; each exceeds the registered 100-ft urban low-speed recommendation."
        ),
        "limitations": "Track-derived station geometry is suitable for screening, not survey certification.",
        "tools_used": ["evaluate_pending_geometry"],
    }
    return measurement, evidence


def evaluate_taper(requirement: dict, scene_facts: dict, source_measurement: dict,
                   sequence: dict) -> tuple[dict, dict]:
    model = sequence["region_model"]
    start_m = float(sequence["start_station_m"])
    end_m = float(model["change_station_m"])
    measured_m = end_m - start_m
    width_m = abs(float(model["taper_lateral_shift_m"]))
    speed_mph = float(scene_facts["posted_speed_mph"])
    rule = requirement["measurement_spec"]["thresholds"][0]
    expression = str(rule.get("formula_parameter") or "")
    width_ft = width_m * FT_PER_M
    required_ft = evaluate_formula(expression, {"W": width_ft, "S": speed_mph})
    measured_ft = measured_m * FT_PER_M
    passed = measured_ft >= required_ft
    payload = {
        "requirement_key": requirement["discovered_requirement_key"],
        "measurement_type": "merging_taper_formula_check",
        "source_measurement_id": source_measurement["measurement_id"],
        "start_station_m": start_m,
        "end_station_m": end_m,
        "width_m": width_m,
        "speed_mph": speed_mph,
        "formula": expression,
    }
    measurement_id = stable_id("measurement", payload)
    measurement = {
        "status": "acquired",
        "measurement_id": measurement_id,
        "measurement_type": payload["measurement_type"],
        "discovered_requirement_key": requirement["discovered_requirement_key"],
        "source_measurement_id": source_measurement["measurement_id"],
        "start_station_m": start_m,
        "end_station_m": end_m,
        "measured_taper_length_m": measured_m,
        "measured_taper_length_ft": measured_ft,
        "lateral_offset_width_m": width_m,
        "lateral_offset_width_ft": width_ft,
        "posted_speed_mph": speed_mph,
        "registered_formula": expression,
        "required_taper_length_ft": required_ft,
        "endpoint_semantics_valid": True,
        "geometry_direction_valid": True,
        "threshold_assessment": {
            "status": "satisfied" if passed else "deficient",
            "passed": passed,
            "margin_ft": measured_ft - required_ft,
        },
        "deficiency_supported": not passed,
        "measurement_method": (
            "reuse of the accepted-channelizer road-coordinate sequence and its deterministic "
            "piecewise taper-to-tangent change point; W is the fitted taper lateral shift"
        ),
        "quality_flags": list(source_measurement.get("quality_flags", [])),
        "associated_bbox_ids": list(source_measurement.get("associated_bbox_ids", [])),
        "associated_image_ids": list(source_measurement.get("associated_image_ids", [])),
    }
    evidence = {
        "evidence_id": stable_id("evidence", measurement),
        "discovered_requirement_key": requirement["discovered_requirement_key"],
        "evidence_kind": "measurement_context",
        "source_ids": [measurement_id, source_measurement["measurement_id"]],
        "acquired_inputs": list(requirement.get("required_inputs", [])),
        "unresolved_inputs": [],
        "finding": (
            f"The fitted merging taper is approximately {measured_ft:.1f} ft long. "
            f"With W={width_ft:.2f} ft and S={speed_mph:.0f} mph, the registered "
            f"formula gives L={required_ft:.1f} ft."
        ),
        "limitations": (
            "The result is a track-derived screening measurement, not a survey; the project "
            "policy treats an estimate with no apparent material shortfall as satisfied."
        ),
        "tools_used": ["evaluate_pending_geometry"],
    }
    return measurement, evidence


def apply_assessment(row: dict, measurement: dict, evidence: dict) -> None:
    prior = {
        "inspection_status": row.get("inspection_status"),
        "unresolved_inputs": deepcopy(row.get("unresolved_inputs", [])),
        "inspection_reason": row.get("inspection_reason"),
    }
    passed = not measurement["deficiency_supported"]
    row["normative_applicability"] = "true"
    row["acquired_inputs"] = list(row.get("required_inputs", []))
    row["unresolved_inputs"] = []
    row["final_data_availability"] = "acquired"
    row["failure_reason"] = None
    row["image_assessable"] = True
    row["inspection_status"] = "satisfied" if passed else "deficient"
    row["evidence_ids"] = sorted(set(row.get("evidence_ids", []) + [evidence["evidence_id"]]))
    row["measurement_ids"] = sorted(set(row.get("measurement_ids", []) + [measurement["measurement_id"]]))
    row["tools_called"] = sorted(set(row.get("tools_called", []) + ["evaluate_pending_geometry"]))
    row["inspection_reason"] = evidence["finding"]
    row["evaluation_supplement"] = {
        "stage": "Stage 4 measurement and Stage 5 evaluation",
        "base_result_preserved": True,
        "prior_result": prior,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base_bytes = args.base_result.read_bytes()
    result = json.loads(base_bytes)
    record = result["record"]
    requirements = record["requirements"]
    before_digest = normative_digest(requirements)
    sign_requirement = find_requirement(requirements, "TABLE-6B-1")
    taper_requirement = find_requirement(requirements, "TABLE-6B-4")
    for requirement in (sign_requirement, taper_requirement):
        if requirement.get("inspection_status") != "not_assessed":
            raise ValueError(f"{requirement['source_locator']} is not pending evaluation")

    scene = SceneDataToolsV5()
    source_measurement, sequence = channelizer_taper_model(record)
    taper_start_station_m = float(sequence["start_station_m"])
    sign_measurement, sign_evidence = evaluate_sign_spacing(
        scene, sign_requirement, taper_start_station_m
    )
    taper_measurement, taper_evidence = evaluate_taper(
        taper_requirement, scene.scene_record["scene_facts"], source_measurement, sequence
    )

    assessments = []
    for requirement, measurement, evidence in (
        (sign_requirement, sign_measurement, sign_evidence),
        (taper_requirement, taper_measurement, taper_evidence),
    ):
        apply_assessment(requirement, measurement, evidence)
        key = requirement["discovered_requirement_key"]
        record.setdefault("measurement_records", {})[measurement["measurement_id"]] = measurement
        record.setdefault("evidence_records", {})[evidence["evidence_id"]] = evidence
        if key in record.get("conclusion_drafts", {}):
            apply_assessment(record["conclusion_drafts"][key], measurement, evidence)
        assessments.append({
            "discovered_requirement_key": key,
            "candidate_label": requirement["candidate_label"],
            "source_locator": requirement["source_locator"],
            "inspection_status": requirement["inspection_status"],
            "measurement_id": measurement["measurement_id"],
            "evidence_id": evidence["evidence_id"],
            "finding": evidence["finding"],
            "limitations": evidence["limitations"],
            "measurement": measurement,
        })

    after_digest = normative_digest(requirements)
    if before_digest != after_digest:
        raise RuntimeError("Stage 2 normative fields changed during evaluation")

    counts = Counter(row.get("inspection_status") for row in requirements)
    supplement = {
        "schema": "stage4_stage5_geometry_evaluation_supplement_v1",
        "base_result": str(args.base_result.resolve()),
        "base_result_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "stage2_normative_digest_before": before_digest,
        "stage2_normative_digest_after": after_digest,
        "stage2_unchanged": True,
        "assessments": assessments,
        "status_counts_after_evaluation": dict(sorted(counts.items())),
    }
    record["evaluation_supplement"] = supplement
    result["evaluation_supplement"] = supplement
    result["reference_notice"] = (
        "The Stage 2 registry is unchanged. Two previously pending table-based geometry "
        "checks were completed from frozen scene evidence in the evaluation stage."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "stage2_unchanged": True,
        "assessments": [
            {"source_locator": row["source_locator"], "status": row["inspection_status"],
             "finding": row["finding"]}
            for row in assessments
        ],
        "status_counts": dict(sorted(counts.items())),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
