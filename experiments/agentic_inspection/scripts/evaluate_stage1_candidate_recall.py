#!/usr/bin/env python3
"""Evaluate whether Stage 1 surfaced the corrected Case 1 source nodes."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


STAGE1_TOOLS = {
    "load_ta_core_graph", "load_scene_condition_graph",
    "load_domain_gap_candidates", "audit_graph_gaps",
}


def _gold_sources(item: dict) -> set[str]:
    values = item.get("source_node_ids") or [
        item.get("primary_source_node_id") or item.get("source_node_id")
    ]
    return {value for value in values if value}


def evaluate(trace_path: Path, gold_path: Path) -> dict:
    trace = json.loads(trace_path.read_text())
    gold = json.loads(gold_path.read_text())
    first_seen: dict[str, dict] = {}
    domain_counts: Counter[str] = Counter()
    for row in trace:
        if row.get("tool") not in STAGE1_TOOLS:
            continue
        result = row.get("result", {})
        if result.get("status") == "failure":
            continue
        items = result.get("candidates", result.get("items", []))
        domain = row.get("arguments", {}).get("domain") or result.get("layer")
        domain_counts[str(domain)] += len(items)
        for rank, item in enumerate(items, 1):
            node_id = item.get("source_node_id")
            if node_id and node_id not in first_seen:
                first_seen[node_id] = {
                    "tool": row["tool"], "domain_or_layer": domain,
                    "rank_in_call": rank,
                    "retrieval_score": item.get("gap_dense_score", item.get("gap_bm25_score")),
                }
    expected = gold["requirements"]
    surfaced = [row for row in expected if _gold_sources(row) & set(first_seen)]
    surfaced_ids = {row["id"] for row in surfaced}
    by_class_expected = Counter(row["normative_level"] for row in expected)
    by_class_surfaced = Counter(row["normative_level"] for row in surfaced)
    invalid = [
        {**row, "first_seen": first_seen[row["source_node_id"]]}
        for row in gold["excluded_invalid_activations"]
        if row["source_node_id"] in first_seen
    ]
    details = [{
        "expected_id": row["id"],
        "source_node_ids": sorted(_gold_sources(row)),
        "surfaced": row["id"] in surfaced_ids,
        "first_seen": next((first_seen[node_id] for node_id in _gold_sources(row)
                            if node_id in first_seen), None),
    } for row in expected]
    return {
        "schema": "case1_stage1_candidate_evaluation_v1",
        "expected_count": len(expected),
        "unique_candidate_count": len(first_seen),
        "surfaced_count": len(surfaced),
        "candidate_recall": len(surfaced) / len(expected) if expected else 0.0,
        "mandatory": {
            "expected": by_class_expected["mandatory"],
            "surfaced": by_class_surfaced["mandatory"],
            "recall": by_class_surfaced["mandatory"] / by_class_expected["mandatory"],
        },
        "guidance": {
            "expected": by_class_expected["guidance"],
            "surfaced": by_class_surfaced["guidance"],
            "recall": by_class_surfaced["guidance"] / by_class_expected["guidance"],
        },
        "missed_expected_ids": [row["id"] for row in expected if row["id"] not in surfaced_ids],
        "known_invalid_candidate_count": len(invalid),
        "known_invalid_candidates": invalid,
        "gold_candidate_density": len(surfaced) / len(first_seen) if first_seen else 0.0,
        "returned_counts_by_domain_or_layer": dict(sorted(domain_counts.items())),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.trace, args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
