#!/usr/bin/env python3
"""Evaluate Stage 1 and Stage 2 separately against a frozen Case 1 gold set."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from evaluate_stage1_stage2_six_domain import _source_integrity
from scoring_common import similarity, subject_similarity


STAGE1_TOOLS = {
    "load_ta_core_graph", "load_scene_condition_graph",
    "load_domain_gap_candidates", "audit_graph_gaps",
}


def _gold_sources(item: dict) -> set[str]:
    values = item.get("source_node_ids") or [
        item.get("primary_source_node_id") or item.get("source_node_id")
    ]
    return {value for value in values if value}


def _stage1_sources(trace: list[dict]) -> set[str]:
    surfaced: set[str] = set()
    for event in trace:
        if event.get("tool") not in STAGE1_TOOLS:
            continue
        result = event.get("result") or {}
        if result.get("status") == "failure":
            continue
        for row in result.get("candidates", result.get("items", [])):
            node_id = row.get("source_node_id")
            if node_id:
                surfaced.add(node_id)
    return surfaced


def _text(row: dict) -> str:
    return " ".join(str(row.get(key) or "") for key in (
        "candidate_label", "subject", "relation", "threshold",
        "applicability_conditions",
    ))


def evaluate(registry_path: Path, trace_path: Path, gold_path: Path) -> dict:
    registry = json.loads(registry_path.read_text())
    trace = json.loads(trace_path.read_text())
    gold = json.loads(gold_path.read_text())
    predicted = registry.get("requirements", [])
    expected = gold["requirements"]
    stage1_sources = _stage1_sources(trace)
    matches = []
    used_predictions: set[int] = set()
    for item in expected:
        expected_modality = "shall" if item["normative_level"] == "mandatory" else "should"
        candidates = []
        for index, row in enumerate(predicted):
            if index in used_predictions:
                continue
            matched_sources = _gold_sources(item) & set(row.get("source_node_ids", []))
            if not matched_sources:
                continue
            if row.get("modality") != expected_modality:
                continue
            semantic = max(
                similarity(item["requirement"], _text(row)),
                subject_similarity(item["requirement"], _text(row)),
            )
            candidates.append((semantic, index, row, sorted(matched_sources)[0]))
        if not candidates:
            continue
        semantic, index, row, matched_source = max(candidates, key=lambda value: value[0])
        if semantic < 0.22:
            continue
        used_predictions.add(index)
        matches.append({
            "expected_id": item["id"],
            "discovered_requirement_key": row.get("discovered_requirement_key"),
            "normative_level": item["normative_level"],
            "semantic_score": round(float(semantic), 4),
            "source_node_id": matched_source,
        })

    matched_ids = {row["expected_id"] for row in matches}
    expected_by_class = Counter(row["normative_level"] for row in expected)
    matched_by_class = Counter(row["normative_level"] for row in matches)
    excluded_by_node = {row["source_node_id"]: row
                        for row in gold.get("excluded_invalid_activations", [])}
    invalid_activations = []
    for row in predicted:
        for node_id in row.get("source_node_ids", []):
            if node_id in excluded_by_node:
                invalid_activations.append({
                    "excluded_id": excluded_by_node[node_id]["id"],
                    "discovered_requirement_key": row.get("discovered_requirement_key"),
                    "source_node_id": node_id,
                })
    unmatched = [
        row.get("discovered_requirement_key") for index, row in enumerate(predicted)
        if index not in used_predictions
    ]
    source_integrity = _source_integrity(predicted, trace)
    recall = len(matches) / len(expected) if expected else 0.0
    activation_precision = len(matches) / len(predicted) if predicted else 0.0
    surfaced_items = [row for row in expected if _gold_sources(row) & stage1_sources]
    surfaced_ids = {row["id"] for row in surfaced_items}
    compiled_surfaced = matched_ids & surfaced_ids
    return {
        "schema": "case1_active_requirement_evaluation_v2",
        "passed": (
            len(matches) == len(expected) and not invalid_activations and
            source_integrity["passed"]
        ),
        "expected_count": len(expected),
        "discovered_count": len(predicted),
        "matched_count": len(matches),
        "overall_recall": recall,
        "activation_precision": activation_precision,
        "stage_metrics": {
            "stage1_candidate_recall": (
                len(surfaced_items) / len(expected) if expected else 0.0
            ),
            "stage1_surfaced_count": len(surfaced_items),
            "stage1_missed_expected_ids": [
                row["id"] for row in expected if row["id"] not in surfaced_ids
            ],
            "stage2_compilation_recall_among_surfaced": (
                len(compiled_surfaced) / len(surfaced_items) if surfaced_items else 0.0
            ),
            "stage2_compiled_surfaced_count": len(compiled_surfaced),
            "end_to_end_registered_recall": recall,
        },
        "mandatory": {
            "expected": expected_by_class["mandatory"],
            "matched": matched_by_class["mandatory"],
            "recall": (matched_by_class["mandatory"] / expected_by_class["mandatory"]
                       if expected_by_class["mandatory"] else 0.0),
        },
        "guidance": {
            "expected": expected_by_class["guidance"],
            "matched": matched_by_class["guidance"],
            "recall": (matched_by_class["guidance"] / expected_by_class["guidance"]
                       if expected_by_class["guidance"] else 0.0),
        },
        "missed_expected_ids": [row["id"] for row in expected if row["id"] not in matched_ids],
        "invalid_activation_count": len(invalid_activations),
        "invalid_activations": invalid_activations,
        "unmatched_prediction_count": len(unmatched),
        "unmatched_prediction_keys": unmatched,
        "source_integrity": source_integrity,
        "matches": matches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.registry, args.trace, args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
