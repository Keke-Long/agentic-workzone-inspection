#!/usr/bin/env python3
"""Evaluate the concise problem-family output without exposing it to the agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from evaluate_stage1_stage2_six_domain import (
    DEFAULT_CHECKLIST, _citation_match, _source_integrity,
)
from project_common import ROOT
from scoring_common import similarity, subject_similarity
from srag_bm25_retrieval_v5 import StructuredBM25V5
from srag_bm25_tools_v5 import _project_scope_exclusion


CORE_PROBLEM_FAMILIES = [
    {"family": "lane_closure_merging_transition", "members": ["LAYOUT-01"]},
    {"family": "left_lane_centerline_channelization", "members": ["LAYOUT-02"]},
    {"family": "lane_closed_advance_sign", "members": ["SIGN-01"]},
    {"family": "left_lane_legend_and_direction", "members": ["SIGN-02", "SIGN-05"]},
    {"family": "road_work_advance_sign", "members": ["SIGN-03"]},
    {"family": "channelizer_taper_and_tangent_spacing", "members": ["CHAN-02", "CHAN-03"]},
    {"family": "channelizer_maintenance", "members": ["CHAN-04"]},
    {"family": "channelizer_serviceability_replacement", "members": ["CHAN-05"]},
    {"family": "merging_taper_adequacy", "members": ["TAPER-04"]},
    {"family": "arrow_board_mode_and_direction", "members": ["ACTIVE-AB-01"]},
    {"family": "arrow_board_taper_start_placement", "members": ["ACTIVE-AB-02"]},
]
SUPPLEMENTAL_GUIDANCE_IDS = ["SIGN-04", "ACTIVE-AB-03"]


def _check_text(row: dict) -> str:
    return " ".join(str(row.get(key) or "") for key in (
        "candidate_label", "subject", "relation", "threshold",
        "applicability_conditions", "measurement_spec",
    ))


def _match_families(families: list[dict], by_id: dict, predicted: list[dict]) -> list[dict]:
    if not families or not predicted:
        return []
    scores = np.zeros((len(families), len(predicted)))
    details = {}
    for fi, family in enumerate(families):
        expected_rows = [by_id[item] for item in family["members"]]
        expected_modality = ("shall" if expected_rows[0]["normative_level"] == "mandatory"
                             else "should")
        for pi, check in enumerate(predicted):
            text = _check_text(check)
            semantic = max(
                max(similarity(row["requirement"], text),
                    subject_similarity(row["requirement"], text))
                for row in expected_rows
            )
            citation = max(
                _citation_match(row["mutcd_sources"], check.get("source_locator", ""))
                for row in expected_rows
            )
            modality_ok = check.get("modality") == expected_modality
            branch_ok = True
            lowered = text.lower()
            if family["family"] == "channelizer_taper_and_tangent_spacing":
                branch_ok = "taper" in lowered and "tangent" in lowered
            if family["family"] == "left_lane_legend_and_direction":
                branch_ok = "left" in lowered and ("legend" in lowered or "direction" in lowered)
            score = (0.72 * semantic + 0.28 * citation
                     if modality_ok and branch_ok else 0.0)
            scores[fi, pi] = score
            details[(fi, pi)] = (semantic, citation, modality_ok, branch_ok)
    rows, cols = linear_sum_assignment(-scores)
    matches = []
    for fi, pi in zip(rows, cols):
        semantic, citation, modality_ok, branch_ok = details[(int(fi), int(pi))]
        score = float(scores[fi, pi])
        if modality_ok and branch_ok and citation >= 0.55 and semantic >= 0.22 and score >= 0.42:
            matches.append({
                "family": families[int(fi)]["family"],
                "member_ids": families[int(fi)]["members"],
                "discovered_requirement_key": predicted[int(pi)].get("discovered_requirement_key"),
                "semantic_score": round(semantic, 4),
                "citation_score": round(citation, 4),
                "combined_score": round(score, 4),
                "prediction_index": int(pi),
            })
    return matches


def evaluate(registry_path: Path, trace_path: Path, checklist_path: Path) -> dict:
    registry = json.loads(registry_path.read_text())
    trace = json.loads(trace_path.read_text())
    checklist = json.loads(checklist_path.read_text())
    by_id = {row["id"]: row for row in checklist["requirements"]}
    predicted = registry.get("requirements", [])
    matches = _match_families(CORE_PROBLEM_FAMILIES, by_id, predicted)
    matched_families = {row["family"] for row in matches}
    matched_predictions = {row["prediction_index"] for row in matches}
    source_integrity = _source_integrity(predicted, trace)

    retrieval = StructuredBM25V5()
    canonical = {row["node_id"]: retrieval._node_view(row)
                 for row in retrieval.index["atomic_nodes"]}
    scope_violations = []
    for row in predicted:
        for node_id in row.get("source_node_ids", []):
            category = _project_scope_exclusion(canonical.get(node_id, {}))
            if category:
                scope_violations.append({
                    "discovered_requirement_key": row.get("discovered_requirement_key"),
                    "category": category,
                })

    supplemental_families = [
        {"family": f"supplemental_{item.lower()}", "members": [item]}
        for item in SUPPLEMENTAL_GUIDANCE_IDS
    ]
    supplemental_matches = _match_families(supplemental_families, by_id, predicted)
    core_recall = len(matches) / len(CORE_PROBLEM_FAMILIES)
    passed = (
        len(matches) == len(CORE_PROBLEM_FAMILIES) and
        source_integrity["passed"] and not scope_violations and
        len(predicted) <= 15
    )
    return {
        "schema_version": "simplified_inspection_check_evaluation_v1",
        "passed": passed,
        "registered_check_count": len(predicted),
        "recommended_maximum_check_count": 15,
        "core_problem_family_count": len(CORE_PROBLEM_FAMILIES),
        "matched_core_problem_family_count": len(matches),
        "core_problem_family_recall": core_recall,
        "missed_core_problem_families": [
            row["family"] for row in CORE_PROBLEM_FAMILIES
            if row["family"] not in matched_families
        ],
        "source_integrity": source_integrity,
        "project_scope_violation_count": len(scope_violations),
        "project_scope_violations": scope_violations,
        "unmatched_check_count": len(predicted) - len(matched_predictions),
        "unmatched_check_keys": [
            row.get("discovered_requirement_key") for index, row in enumerate(predicted)
            if index not in matched_predictions
        ],
        "supplemental_guidance": {
            "expected_ids": SUPPLEMENTAL_GUIDANCE_IDS,
            "matched_count": len(supplemental_matches),
            "matches": [{key: value for key, value in row.items()
                         if key != "prediction_index"} for row in supplemental_matches],
        },
        "matches": [{key: value for key, value in row.items()
                     if key != "prediction_index"} for row in matches],
        "pass_rule": "11/11 core problem families, 100% source integrity, zero project-scope violations, and no more than 15 concise checks",
        "note": "The 11 problem families are evaluator-only groupings of the fixed checklist; they are never exposed to the agent.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.registry, args.trace, args.checklist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
