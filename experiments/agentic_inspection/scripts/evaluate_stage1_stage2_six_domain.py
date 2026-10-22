#!/usr/bin/env python3
"""Posthoc evaluator for the isolated six-domain Stage 1-2 canary.

The fixed checklist is opened only by this evaluator, after model execution.
Predictions are matched one-to-one by natural-language proposition and citation;
the agent never receives checklist IDs or target counts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from project_common import ROOT
from scoring_common import similarity, subject_similarity
from srag_bm25_retrieval_v5 import StructuredBM25V5


DEFAULT_RUN = ROOT / "artifacts/workzone_01/benchmark/stage1_stage2/kg_plus_bm25/scene-CATS-01"
DEFAULT_CHECKLIST = ROOT / "ground_truth/workzone_fixed_coverage_checklist.json"


def _source_key(value: str) -> tuple[str | None, str | None]:
    text = value.upper().replace("SEC-", "").replace("SECTION ", "")
    section = re.search(r"\b(6[A-Z]\.[0-9]{2})\b", text)
    paragraph = re.search(r"(?:PARAGRAPH|PARA\.?|¶)\s*([0-9]{1,2})", text)
    return (section.group(1) if section else None,
            paragraph.group(1).zfill(2) if paragraph else None)


def _citation_match(gold_sources: list[str], predicted_locator: str) -> float:
    predicted = _source_key(predicted_locator)
    best = 0.0
    for source in gold_sources:
        gold = _source_key(source)
        if gold[0] and predicted[0] == gold[0]:
            best = max(best, 1.0 if gold[1] is None or predicted[1] == gold[1] else 0.0)
        elif source.lower().startswith("table") and source.lower() in predicted_locator.lower():
            best = 1.0
    return best


def _prediction_text(row: dict) -> str:
    return " ".join(str(row.get(key) or "") for key in (
        "candidate_label", "subject", "relation", "threshold", "applicability_conditions"
    ))


def _semantic_score(gold: dict, predicted: dict) -> float:
    expected = gold["requirement"]
    actual = _prediction_text(predicted)
    return max(similarity(expected, actual), subject_similarity(expected, actual))


def _match(gold: list[dict], predicted: list[dict]) -> list[dict]:
    if not gold or not predicted:
        return []
    scores = np.zeros((len(gold), len(predicted)))
    details: dict[tuple[int, int], tuple[float, float, bool]] = {}
    for gi, expected in enumerate(gold):
        expected_modality = "shall" if expected["normative_level"] == "mandatory" else "should"
        for pi, actual in enumerate(predicted):
            semantic = _semantic_score(expected, actual)
            citation = _citation_match(expected["mutcd_sources"], actual.get("source_locator", ""))
            modality_ok = actual.get("modality") == expected_modality
            score = 0.72 * semantic + 0.28 * citation if modality_ok else 0.0
            scores[gi, pi] = score
            details[(gi, pi)] = (semantic, citation, modality_ok)
    rows, cols = linear_sum_assignment(-scores)
    matches = []
    for gi, pi in zip(rows, cols):
        semantic, citation, modality_ok = details[(int(gi), int(pi))]
        score = float(scores[gi, pi])
        if modality_ok and citation >= 0.55 and semantic >= 0.22 and score >= 0.42:
            matches.append({
                "expected_id": gold[int(gi)]["id"],
                "discovered_requirement_key": predicted[int(pi)].get("discovered_requirement_key"),
                "normative_level": gold[int(gi)]["normative_level"],
                "semantic_score": round(semantic, 4), "citation_score": round(citation, 4),
                "combined_score": round(score, 4), "gold_index": int(gi), "prediction_index": int(pi),
            })
    return matches


def _source_integrity(predicted: list[dict], trace: list[dict]) -> dict:
    retrieved_ids: set[str] = set()
    for event in trace:
        if event.get("tool") not in {"search_manual", "search_manual_for_need", "expand_source_unit",
                                     "expand_source_unit_for_need",
                                     "follow_cross_reference", "read_source_node",
                                     "load_ta_core_graph", "load_scene_condition_graph",
                                     "audit_graph_gaps", "load_domain_gap_candidates"}:
            continue
        result = event.get("result", {})
        for item in (result.get("items", []) + result.get("atomic_items", []) +
                     result.get("candidates", [])):
            node_id = item.get("source_node_id")
            if node_id:
                retrieved_ids.add(node_id)
    retrieval = StructuredBM25V5()
    canonical_nodes = {
        row["node_id"]: retrieval._node_view(row)
        for row in retrieval.index["atomic_nodes"]
    }
    failures = []
    for row in predicted:
        node_ids = row.get("source_node_ids", [])
        nodes = [canonical_nodes.get(node_id) if node_id in retrieved_ids else None
                 for node_id in node_ids]
        if not nodes or any(node is None for node in nodes):
            failures.append({"key": row.get("discovered_requirement_key"), "reason": "source_not_retrieved"})
            continue
        submitted_locator = row.get("source_locator") or ""
        matching = []
        for node in nodes:
            canonical_locator = node.get("source_locator") or ""
            exact = canonical_locator == submitted_locator
            figure_basis_extension = (
                node.get("node_type") == "figure_component" and
                node.get("normative_basis") and
                submitted_locator.startswith(canonical_locator + "; Guidance basis ")
            )
            if exact or figure_basis_extension:
                matching.append(node)
        if not matching:
            failures.append({"key": row.get("discovered_requirement_key"), "reason": "locator_mismatch"})
            continue
        canonical_span = (matching[0].get("source_span") or "").strip()
        span = (row.get("source_span") or "").strip()
        if not span or (span not in canonical_span and canonical_span not in span):
            failures.append({"key": row.get("discovered_requirement_key"), "reason": "span_mismatch"})
        source_modality = {"standard": "shall", "shall": "shall",
                           "guidance": "should", "should": "should"}.get(
                               str(matching[0].get("modality", "")).lower()
                           )
        if source_modality != row.get("modality"):
            failures.append({"key": row.get("discovered_requirement_key"), "reason": "modality_mismatch"})
    return {"passed": not failures, "verified_count": len(predicted) - len(failures), "failures": failures}


def _duplicate_pairs(predicted: list[dict], matched_expected_by_prediction: dict[int, str]) -> list[dict]:
    duplicates = []
    for left in range(len(predicted)):
        for right in range(left + 1, len(predicted)):
            if (left in matched_expected_by_prediction and right in matched_expected_by_prediction and
                    matched_expected_by_prediction[left] != matched_expected_by_prediction[right]):
                continue
            same_modality = predicted[left].get("modality") == predicted[right].get("modality")
            same_source = _source_key(predicted[left].get("source_locator", "")) == _source_key(
                predicted[right].get("source_locator", ""))
            score = similarity(_prediction_text(predicted[left]), _prediction_text(predicted[right]))
            if same_modality and same_source and score >= 0.82:
                duplicates.append({"left": predicted[left].get("discovered_requirement_key"),
                                   "right": predicted[right].get("discovered_requirement_key"),
                                   "similarity": round(score, 4)})
    return duplicates


def _atomicity_flags(predicted: list[dict], matched_prediction_indexes: set[int]) -> list[dict]:
    flags = []
    separators = re.compile(r"\b(?:and|as well as)\b|;")
    for index, row in enumerate(predicted):
        if index in matched_prediction_indexes:
            continue
        predicate = " ".join(str(row.get(key) or "") for key in ("relation", "threshold"))
        # This is deliberately a conservative review flag, not an automatic failure
        # for ordinary noun phrases such as "clean and visible".
        if (len(separators.findall(predicate.lower())) >= 2 or
                "with devices spaced" in predicate.lower()):
            flags.append({"key": row.get("discovered_requirement_key"),
                          "reason": "multiple conjunctions in normative predicate"})
    return flags


def evaluate(registry_path: Path, trace_path: Path, checklist_path: Path) -> dict:
    registry = json.loads(registry_path.read_text())
    trace = json.loads(trace_path.read_text())
    checklist = json.loads(checklist_path.read_text())
    expected_ids = checklist["stage1_stage2_test_profile"]["expected_activated_requirement_ids"]
    by_id = {row["id"]: row for row in checklist["requirements"]}
    gold = [by_id[item] for item in expected_ids]
    predicted = registry.get("requirements", [])
    matches = _match(gold, predicted)
    matched_ids = {row["expected_id"] for row in matches}
    matched_predictions = {row["prediction_index"] for row in matches}
    matched_expected_by_prediction = {row["prediction_index"]: row["expected_id"] for row in matches}
    mandatory = [row for row in gold if row["normative_level"] == "mandatory"]
    guidance = [row for row in gold if row["normative_level"] == "guidance"]
    mandatory_hits = sum(row["id"] in matched_ids for row in mandatory)
    guidance_hits = sum(row["id"] in matched_ids for row in guidance)
    source_integrity = _source_integrity(predicted, trace)
    duplicates = _duplicate_pairs(predicted, matched_expected_by_prediction)
    atomicity_flags = _atomicity_flags(predicted, matched_predictions)
    modality_correct = sum(
        predicted[row["prediction_index"]].get("modality") ==
        ("shall" if by_id[row["expected_id"]]["normative_level"] == "mandatory" else "should")
        for row in matches
    )
    unmatched_prediction_count = len(predicted) - len(matched_predictions)
    complete = (len(matches) == len(gold) and unmatched_prediction_count == 0 and
                source_integrity["passed"] and not duplicates and not atomicity_flags)
    return {
        "schema_version": "stage1_stage2_six_domain_evaluation_v1",
        "profile_id": checklist["stage1_stage2_test_profile"]["profile_id"],
        "passed": complete,
        "expected_count": len(gold), "discovered_count": len(predicted), "matched_count": len(matches),
        "mandatory": {"expected": len(mandatory), "matched": mandatory_hits,
                      "recall": mandatory_hits / len(mandatory) if mandatory else 1.0},
        "guidance": {"expected": len(guidance), "matched": guidance_hits,
                     "recall": guidance_hits / len(guidance) if guidance else 1.0},
        "overall_recall": len(matches) / len(gold) if gold else 1.0,
        "activation_precision": len(matches) / len(predicted) if predicted else 0.0,
        "modality_accuracy_on_matches": modality_correct / len(matches) if matches else 0.0,
        "source_integrity": source_integrity,
        "semantic_duplicate_count": len(duplicates), "semantic_duplicates": duplicates,
        "atomicity_review_flag_count": len(atomicity_flags), "atomicity_review_flags": atomicity_flags,
        "missed_expected_ids": [item for item in expected_ids if item not in matched_ids],
        "unmatched_prediction_keys": [row.get("discovered_requirement_key") for index, row in enumerate(predicted)
                                      if index not in matched_predictions],
        "matches": [{key: value for key, value in row.items()
                     if key not in {"gold_index", "prediction_index"}} for row in matches],
        "pass_rule": "100% mandatory/guidance recall and activation precision, 100% source integrity, zero semantic duplicates, and zero atomicity flags",
        "note": "Atomicity flags apply to unmatched predictions and identify compound or broad predicates requiring review."
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_RUN / "stage_1_to_6_registry.json")
    parser.add_argument("--trace", type=Path, default=DEFAULT_RUN / "tool_trace.json")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_RUN / "stage1_stage2_evaluation.json")
    args = parser.parse_args()
    result = evaluate(args.registry, args.trace, args.checklist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
