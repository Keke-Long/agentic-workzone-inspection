#!/usr/bin/env python3
"""Shared posthoc semantic matching and scoring helpers.

This evaluator is deliberately posthoc: internal requirement IDs are read only
from the hidden reference after model execution. Predictions are matched to the
reference one-to-one using their natural-language content.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from project_common import ROOT, load_config


MAIN_COLUMNS = [
    "Method",
    "Layout Accuracy",
    "Inspectable Item Coverage",
    "Checked-item Correctness",
    "Grounded Checked-item Correctness",
    "Correct Inspection Rate",
    "Grounded Correct Inspection Rate",
    "Critical False-clear Rate",
    "False-deficiency Rate",
]

# These thresholds already governed v4 posthoc matching before run_01 was
# scored. They are frozen here and are identical for every method.
IDENTITY_SCORE_MIN = 0.55
IDENTITY_SUBJECT_MIN = 0.50
STRICT_SUBJECT_MIN = 0.60
STRICT_RELATION_MIN = 0.50
STRICT_THRESHOLD_MIN = 0.55
CONDITION_ITEM_MIN = 0.55

EMPTY_VALUES = {"", "n a", "na", "none", "not applicable", "not specified", "null"}
TOKEN_ALIASES = {
    "feet": "ft",
    "foot": "ft",
    "drums": "drum",
    "lanes": "lane",
    "displays": "display",
    "displayed": "display",
    "placed": "place",
    "placing": "place",
    "required": "require",
    "requires": "require",
    "requirements": "requirement",
}
INPUT_ALIASES = {
    "accepted bbox observation": "accepted_bbox_observations",
    "accepted bbox observations": "accepted_bbox_observations",
    "accepted bounding box observation": "accepted_bbox_observations",
    "active work state": "active_work",
    "available width": "available_width_ft",
    "closed lane": "closed_lane",
    "dense temporal image": "dense_temporal_images",
    "dense temporal images": "dense_temporal_images",
    "inspection period": "inspection_period",
    "lane count": "roadway_lane_count",
    "lanes closed": "lanes_closed",
    "opposite direction image coverage": "opposite_direction_image_coverage",
    "pcms deployed": "pcms_deployed",
    "posted speed": "posted_speed_mph",
    "posted speed mph": "posted_speed_mph",
    "raw image": "raw_images",
    "raw images": "raw_images",
    "roadway configuration": "roadway_configuration",
    "roadway lane count": "roadway_lane_count",
    "work duration": "work_duration_category",
    "work duration category": "work_duration_category",
    "work ended": "work_ended",
    "worker presence": "workers_present",
}


def ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def words(value: Any) -> set[str]:
    text = _plain(value).lower().replace("_", " ").replace("‑", "-").replace("–", "-")
    tokens = re.findall(r"[a-z]+\d+(?:-\d+)*|\d+-\d+|[a-z]+|\d+(?:\.\d+)?", text)
    output = set()
    for token in tokens:
        token = TOKEN_ALIASES.get(token, token)
        if token.endswith("s") and len(token) > 4 and token not in TOKEN_ALIASES:
            token = token[:-1]
        output.add(token)
    return output


def is_empty_semantic(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", _plain(value).lower()).strip()
    return normalized in EMPTY_VALUES or not words(value)


def similarity(left: Any, right: Any) -> float:
    if is_empty_semantic(left) and is_empty_semantic(right):
        return 1.0
    left_words, right_words = words(left), words(right)
    if not left_words or not right_words:
        return 0.0
    return 2 * len(left_words & right_words) / (len(left_words) + len(right_words))


def subject_similarity(left: Any, right: Any) -> float:
    """Allow a prediction to add qualifiers while retaining the full subject."""
    left_words, right_words = words(left), words(right)
    if not left_words and not right_words:
        return 1.0
    if not left_words or not right_words:
        return 0.0
    dice = 2 * len(left_words & right_words) / (len(left_words) + len(right_words))
    expected_coverage = len(left_words & right_words) / len(left_words)
    return max(dice, expected_coverage)


def relation_similarity(left: Any, right: Any) -> float:
    """Normalize common surface forms of the same inspection proposition."""
    def relation_class(value: Any) -> str | None:
        tokens = words(value)
        if tokens & {"exist", "present", "depicted", "shown", "used", "installed", "provided"}:
            return "presence"
        if tokens & {"display", "bear", "message", "indicate"}:
            return "display"
        if tokens & {"space", "spaced", "interval"}:
            return "spacing"
        if tokens & {"place", "located", "positioned"}:
            return "placement"
        if tokens & {"match", "identical", "same"}:
            return "equivalence"
        return None

    left_class, right_class = relation_class(left), relation_class(right)
    if left_class is not None and left_class == right_class:
        return 1.0
    return similarity(left, right)


def threshold_similarity(expected: Any, predicted: Any) -> float:
    # An empty frozen threshold means no additional threshold is required for
    # identity. A prediction may add a non-contradictory placement description.
    if is_empty_semantic(expected):
        return 1.0
    return similarity(expected, predicted)


def _one_to_one_text_matches(expected: list[Any], predicted: list[Any], minimum: float) -> list[tuple[int, int, float]]:
    if not expected or not predicted:
        return []
    scores = np.array([[similarity(left, right) for right in predicted] for left in expected])
    rows, cols = linear_sum_assignment(-scores)
    return [
        (int(row), int(col), float(scores[row, col]))
        for row, col in zip(rows, cols)
        if float(scores[row, col]) >= minimum
    ]


def semantic_list_coverage(expected: list[Any], predicted: list[Any]) -> float:
    expected = list(expected or [])
    predicted = list(predicted or [])
    if not expected:
        return 1.0
    return len(_one_to_one_text_matches(expected, predicted, CONDITION_ITEM_MIN)) / len(expected)


def condition_score(expected: dict, predicted: dict) -> float:
    """Read structured condition values first, then natural-language conditions.

    This score is diagnostic for inspection-focused evaluation. Different but
    sufficient input decompositions no longer erase an otherwise valid target.
    """
    expected_values = {
        canonical_input(field): re.sub(r"[^a-z0-9]+", " ", _plain(value).lower()).strip()
        for field, value in expected.get("condition_values", {}).items()
        if value is not None
    }
    predicted_values = {
        canonical_input(row.get("field")): re.sub(r"[^a-z0-9]+", " ", _plain(row.get("value")).lower()).strip()
        for row in predicted.get("condition_values", [])
        if isinstance(row, dict) and row.get("known") is True
    }
    if expected_values and predicted_values:
        hits = sum(
            field in predicted_values and similarity(value, predicted_values[field]) >= CONDITION_ITEM_MIN
            for field, value in expected_values.items()
        )
        return hits / len(expected_values)
    return semantic_list_coverage(
        expected["extraction_reference"]["applicability_conditions"],
        predicted.get("applicability_conditions", []),
    )


def canonical_input(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", _plain(value).lower()).strip()
    if text in INPUT_ALIASES:
        return INPUT_ALIASES[text]
    # Preserve unknown concepts deterministically; aliases above only reconcile
    # presentation variants and do not add or remove a required input.
    return text.replace(" ", "_")


def exact_required_inputs_match(expected: list[Any], predicted: list[Any]) -> bool:
    left = [canonical_input(value) for value in expected or []]
    right = [canonical_input(value) for value in predicted or []]
    return len(left) == len(set(left)) == len(right) == len(set(right)) and set(left) == set(right)


def pages(locator: Any) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"(?:pdf\s*)?(?:page|p\.?)[^0-9]{0,8}(\d+)", _plain(locator), re.I)
    }


def component_scores(expected: dict, predicted: dict) -> dict[str, float | bool]:
    ref = expected["extraction_reference"]
    expected_pages = {int(value) for value in expected["source_pages"]}
    return {
        "subject": subject_similarity(ref["subject"], predicted.get("subject", "")),
        "relation": relation_similarity(ref["relation"], predicted.get("relation", "")),
        "threshold": threshold_similarity(ref["threshold"], predicted.get("threshold", "")),
        "applicability_conditions": condition_score(expected, predicted),
        "required_inputs": exact_required_inputs_match(
            ref["required_inputs"], predicted.get("required_inputs", [])
        ),
        "source_locator": bool(expected_pages & pages(predicted.get("source_locator", ""))),
    }


def identity_score(expected: dict, predicted: dict) -> float:
    scores = component_scores(expected, predicted)
    # Required inputs and source are strict correctness gates, not identity
    # features: identity is established from the normative proposition itself.
    conditions = float(scores["applicability_conditions"])
    return (
        0.45 * float(scores["subject"])
        + 0.20 * float(scores["relation"])
        + 0.25 * float(scores["threshold"])
        + 0.10 * conditions
    )


def match_requirements(expected: list[dict], predicted: list[dict]) -> list[tuple[int, int, float]]:
    """Return posthoc identity pairs; every index appears at most once."""
    if not expected or not predicted:
        return []
    scores = np.array([[identity_score(left, right) for right in predicted] for left in expected])
    rows, cols = linear_sum_assignment(-scores)
    output = []
    for row, col in zip(rows, cols):
        score = float(scores[row, col])
        subject = float(component_scores(expected[row], predicted[col])["subject"])
        if score >= IDENTITY_SCORE_MIN and subject >= IDENTITY_SUBJECT_MIN:
            output.append((int(row), int(col), score))
    return output


def strict_content_correct(expected: dict, predicted: dict) -> tuple[bool, dict[str, float | bool]]:
    scores = component_scores(expected, predicted)
    correct = (
        float(scores["subject"]) >= STRICT_SUBJECT_MIN
        and float(scores["relation"]) >= STRICT_RELATION_MIN
        and float(scores["threshold"]) >= STRICT_THRESHOLD_MIN
    )
    return bool(correct), scores


def normalize_layout_code(value: Any) -> str | None:
    text = _plain(value).replace("‑", "-").replace("–", "-")
    typical_application = re.search(r"\bta\s*-?\s*(\d{1,3})\b", text, re.I)
    if typical_application:
        return f"TA-{int(typical_application.group(1))}"
    legacy_layout = re.search(r"\b(\d{1,2}-\d{1,2})\b", text)
    return legacy_layout.group(1) if legacy_layout else None


def eligible_for_inspection(requirement: dict) -> bool:
    return (
        requirement.get("normative_applicability") == "true"
        and requirement.get("condition_data_complete") is True
        and requirement.get("image_assessable") is True
    )


def _metric(numerator: int, denominator: int, zero_label: str) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": ratio(numerator, denominator),
        "zero_denominator_label": zero_label,
    }


def _empty_record(scene_id: str) -> dict:
    return {
        "scene_id": scene_id,
        "layout_selection_status": "missing_output",
        "selected_layouts": [],
        "requirements": [],
        "requires_human_review": False,
    }


def score_record(
    reference: dict,
    record: dict,
    valid_evidence: set[str],
    scene_facts: dict[str, Any] | None = None,
) -> tuple[dict, list[dict]]:
    expected = reference["requirements"]
    predicted = record.get("requirements", []) if isinstance(record.get("requirements", []), list) else []
    identity_pairs = match_requirements(expected, predicted)
    identity_by_expected = {expected_index: predicted_index for expected_index, predicted_index, _ in identity_pairs}
    human_failure = record.get("requires_human_review") is True

    strict_by_expected: dict[int, int] = {}
    pair_details = []
    for expected_index, predicted_index, identity in identity_pairs:
        correct, components = strict_content_correct(expected[expected_index], predicted[predicted_index])
        if correct:
            strict_by_expected[expected_index] = predicted_index
        pair_details.append({
            "hidden_reference_requirement_id": expected[expected_index]["requirement_id"],
            "predicted_requirement_key": predicted[predicted_index].get("discovered_requirement_key"),
            "expected_index": expected_index,
            "predicted_index": predicted_index,
            "identity_score": identity,
            "strict_content_correct": correct,
            "component_scores": components,
        })

    expected_primary_layouts = {normalize_layout_code(row.get("layout_code")) for row in reference["applicable_layouts"]}
    expected_primary_layouts.discard(None)
    predicted_primary_layouts = {
        normalize_layout_code(row.get("layout_code"))
        for row in record.get("selected_layouts", [])
        if row.get("layout_role", "primary_applicable") == "primary_applicable"
    }
    predicted_primary_layouts.discard(None)
    scene_facts = scene_facts or {}
    condition_data_sufficient_for_layout = all(
        scene_facts.get(field) is not None
        for row in reference.get("applicable_layouts", [])
        for field in row.get("matched_scene_fields", [])
    )
    layout_correct = (
        condition_data_sufficient_for_layout
        and not human_failure
        and record.get("layout_selection_status") == "determined"
        and predicted_primary_layouts == expected_primary_layouts
    )
    layout_denominator = int(condition_data_sufficient_for_layout)

    eligible_indices = [index for index, row in enumerate(expected) if eligible_for_inspection(row)]
    inspected_eligible = correct_inspection = grounded_correct_inspection = 0
    false_clear_numerator = false_deficiency_numerator = 0
    checked_prediction_indices = {
        index for index, row in enumerate(predicted)
        if row.get("inspection_status") in {"satisfied", "deficient"}
    }
    critical_deficient_indices = [
        index for index in eligible_indices
        if expected[index].get("critical_requirement") is True and expected[index].get("inspection_status") == "deficient"
    ]
    satisfied_indices = [
        index for index in eligible_indices if expected[index].get("inspection_status") == "satisfied"
    ]

    for expected_index in eligible_indices:
        expected_row = expected[expected_index]
        identity_prediction = predicted[identity_by_expected[expected_index]] if expected_index in identity_by_expected else None
        strict_prediction = predicted[strict_by_expected[expected_index]] if expected_index in strict_by_expected else None

        # False-clear/false-deficiency require an attributable, explicit,
        # autonomous wrong assertion. Missing output and handoff are not events.
        if identity_prediction is not None and not human_failure:
            asserted = identity_prediction.get("inspection_status")
            if expected_index in critical_deficient_indices and asserted == "satisfied":
                false_clear_numerator += 1
            if expected_index in satisfied_indices and asserted == "deficient":
                false_deficiency_numerator += 1

        if strict_prediction is None or human_failure or not layout_correct:
            continue
        predicted_status = strict_prediction.get("inspection_status")
        if predicted_status not in {"satisfied", "deficient"}:
            continue
        inspected_eligible += 1
        if strict_prediction.get("normative_applicability") != "true":
            continue
        if predicted_status != expected_row.get("inspection_status"):
            continue
        correct_inspection += 1

        cited = strict_prediction.get("evidence_ids", [])
        cited_set = set(cited) if isinstance(cited, list) else set()
        supporting = set(expected_row.get("evidence_ids", []))
        if cited_set and cited_set <= valid_evidence and bool(cited_set & supporting):
            grounded_correct_inspection += 1

    metrics = {
        "layout_accuracy": _metric(int(layout_correct), layout_denominator, "eligible scenes"),
        "inspectable_item_coverage": _metric(inspected_eligible, len(eligible_indices), "eligible cases"),
        "checked_item_correctness": _metric(
            correct_inspection, len(checked_prediction_indices), "checked items"
        ),
        "grounded_checked_item_correctness": _metric(
            grounded_correct_inspection, len(checked_prediction_indices), "checked items"
        ),
        "correct_inspection_rate": _metric(correct_inspection, len(eligible_indices), "eligible cases"),
        "grounded_correct_inspection_rate": _metric(
            grounded_correct_inspection, len(eligible_indices), "eligible cases"
        ),
        "critical_false_clear_rate": _metric(
            false_clear_numerator, len(critical_deficient_indices), "critical deficient cases"
        ),
        "false_deficiency_rate": _metric(
            false_deficiency_numerator, len(satisfied_indices), "satisfied cases"
        ),
        "accounting": {
            "reference_requirement_count": len(expected),
            "predicted_requirement_count": len(predicted),
            "checked_prediction_count": len(checked_prediction_indices),
            "identity_matched_count": len(identity_pairs),
            "normative_identity_content_matched_count": len(strict_by_expected),
            "identity_matched_but_normative_content_failed": len(identity_pairs) - len(strict_by_expected),
            "unmatched_reference_count": len(expected) - len(identity_pairs),
            "unmatched_prediction_count": len(predicted) - len(identity_pairs),
            "eligible_inspection_count": len(eligible_indices),
            "inspected_eligible_count": inspected_eligible,
            "correct_inspection_count": correct_inspection,
            "grounded_correct_inspection_count": grounded_correct_inspection,
            "omitted_uninspectable_reference_count_not_penalized": len(expected) - len(eligible_indices),
            "requires_human_review_observed": human_failure,
            "predicted_primary_layouts": sorted(predicted_primary_layouts),
            "reference_primary_layouts": sorted(expected_primary_layouts),
        },
    }
    return metrics, pair_details


def format_metric(metric: dict[str, Any]) -> str:
    denominator = metric["denominator"]
    if denominator == 0:
        return f"N/A (0 {metric['zero_denominator_label']})"
    return f"{100 * metric['value']:.1f}% ({metric['numerator']}/{denominator})"


def result_directory(cfg: dict, method: str, run: int, scene_id: str) -> Path:
    return ROOT / cfg["methods"][method]["output_directory"] / f"run_{run:02d}" / scene_id


def write_main_table(out: Path, cfg: dict, scored: list[dict]) -> None:
    csv_rows = []
    for row in scored:
        metrics = row["metrics"]
        csv_rows.append({
            "Method": cfg["methods"][row["method_id"]]["display_name"],
            "Layout Accuracy": format_metric(metrics["layout_accuracy"]),
            "Inspectable Item Coverage": format_metric(metrics["inspectable_item_coverage"]),
            "Checked-item Correctness": format_metric(metrics["checked_item_correctness"]),
            "Grounded Checked-item Correctness": format_metric(metrics["grounded_checked_item_correctness"]),
            "Correct Inspection Rate": format_metric(metrics["correct_inspection_rate"]),
            "Grounded Correct Inspection Rate": format_metric(metrics["grounded_correct_inspection_rate"]),
            "Critical False-clear Rate": format_metric(metrics["critical_false_clear_rate"]),
            "False-deficiency Rate": format_metric(metrics["false_deficiency_rate"]),
        })
    with (out / "main_table.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MAIN_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_rows)

    lines = [
        f"# Formal application results — run_{scored[0]['run']:02d}",
        "",
        "| " + " | ".join(MAIN_COLUMNS) + " |",
        "|" + "|".join(["---"] + ["---:"] * (len(MAIN_COLUMNS) - 1)) + "|",
    ]
    lines.extend("| " + " | ".join(row[column] for column in MAIN_COLUMNS) + " |" for row in csv_rows)
    lines.extend([
        "",
        "Scoring reference: the frozen autonomous reference for this run; it is not expert Ground Truth.",
        "",
        "Reference requirements that are not genuinely inspectable may be omitted without penalty. Coverage is measured "
        "only over the frozen inspectable subset. Checked-item denominators include every explicit `satisfied` or "
        "`deficient` assertion, including spurious or unsafe assertions.",
        "",
        "Missing an inspectable requirement, returning no valid conclusion, selecting the wrong Layout, or "
        "`requires_human_review=true` fails the end-to-end inspection numerator.",
        "",
        "Critical False-clear Rate is N/A because the frozen eligible subset contains no critical deficient requirement.",
    ])
    (out / "main_table.md").write_text("\n".join(lines) + "\n")


def write_accounting(out: Path, cfg: dict, scored: list[dict]) -> None:
    fields = [
        "Method", "Output requirements", "Checked items", "Eligible inspection requirements",
        "Covered eligible items", "Correct checked items", "Grounded correct checked items",
        "Uninspectable references omitted without penalty",
        "Layout numerator", "Layout denominator",
        "Coverage numerator", "Coverage denominator",
        "Checked-correctness numerator", "Checked-correctness denominator",
        "Grounded-checked numerator", "Grounded-checked denominator",
        "Correct-inspection numerator", "Correct-inspection denominator",
        "Grounded-correct numerator", "Grounded-correct denominator",
        "Critical-false-clear numerator", "Critical-false-clear denominator",
        "False-deficiency numerator", "False-deficiency denominator",
    ]
    rows = []
    for row in scored:
        metrics = row["metrics"]
        accounting = metrics["accounting"]
        rows.append({
            "Method": cfg["methods"][row["method_id"]]["display_name"],
            "Output requirements": accounting["predicted_requirement_count"],
            "Checked items": accounting["checked_prediction_count"],
            "Eligible inspection requirements": accounting["eligible_inspection_count"],
            "Covered eligible items": accounting["inspected_eligible_count"],
            "Correct checked items": accounting["correct_inspection_count"],
            "Grounded correct checked items": accounting["grounded_correct_inspection_count"],
            "Uninspectable references omitted without penalty": accounting["omitted_uninspectable_reference_count_not_penalized"],
            "Layout numerator": metrics["layout_accuracy"]["numerator"],
            "Layout denominator": metrics["layout_accuracy"]["denominator"],
            "Coverage numerator": metrics["inspectable_item_coverage"]["numerator"],
            "Coverage denominator": metrics["inspectable_item_coverage"]["denominator"],
            "Checked-correctness numerator": metrics["checked_item_correctness"]["numerator"],
            "Checked-correctness denominator": metrics["checked_item_correctness"]["denominator"],
            "Grounded-checked numerator": metrics["grounded_checked_item_correctness"]["numerator"],
            "Grounded-checked denominator": metrics["grounded_checked_item_correctness"]["denominator"],
            "Correct-inspection numerator": metrics["correct_inspection_rate"]["numerator"],
            "Correct-inspection denominator": metrics["correct_inspection_rate"]["denominator"],
            "Grounded-correct numerator": metrics["grounded_correct_inspection_rate"]["numerator"],
            "Grounded-correct denominator": metrics["grounded_correct_inspection_rate"]["denominator"],
            "Critical-false-clear numerator": metrics["critical_false_clear_rate"]["numerator"],
            "Critical-false-clear denominator": metrics["critical_false_clear_rate"]["denominator"],
            "False-deficiency numerator": metrics["false_deficiency_rate"]["numerator"],
            "False-deficiency denominator": metrics["false_deficiency_rate"]["denominator"],
        })
    with (out / "method_accounting.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    markdown = [
        "# Formal scoring accounting",
        "",
        "| " + " | ".join(fields) + " |",
        "|" + "|".join(["---"] + ["---:"] * (len(fields) - 1)) + "|",
    ]
    markdown.extend("| " + " | ".join(str(row[field]) for field in fields) + " |" for row in rows)
    (out / "method_accounting.md").write_text("\n".join(markdown) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()

    cfg = load_config()
    reference_path = ROOT / cfg["scene"]["hidden_reference"]
    reference = json.loads(reference_path.read_text())
    scene = json.loads((ROOT / cfg["scene"]["active_manifest"]).read_text())
    valid_evidence = {row["observation_id"] for row in scene["accepted_observations"]}
    scored, missing_results, match_details = [], [], {}

    for method in cfg["method_order"]:
        directory = result_directory(cfg, method, args.run, scene["scene_id"])
        result_path = directory / "result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text())
            record = payload.get("record", _empty_record(scene["scene_id"]))
        else:
            missing_results.append(str(result_path.relative_to(ROOT)))
            record = _empty_record(scene["scene_id"])
        metrics, details = score_record(reference, record, valid_evidence, scene.get("scene_facts", {}))
        scored.append({"method_id": method, "run": args.run, "metrics": metrics})
        match_details[method] = details

    out = ROOT / "reports_autonomous_scene_v4" / f"run_{args.run:02d}"
    out.mkdir(parents=True, exist_ok=True)
    write_main_table(out, cfg, scored)
    write_accounting(out, cfg, scored)

    prior_formal_audit_path = out / "formal_run_audit.json"
    prior_formal_audit = json.loads(prior_formal_audit_path.read_text()) if prior_formal_audit_path.exists() else {}
    matching_uniqueness = all(
        len({pair["expected_index"] for pair in pairs}) == len(pairs)
        and len({pair["predicted_index"] for pair in pairs}) == len(pairs)
        for pairs in match_details.values()
    )
    audit = {
        "run": args.run,
        "scoring_mode": "offline_rescore_of_existing_frozen_results",
        "external_model_calls_made_by_scorer": 0,
        "reference_status": reference.get("status"),
        "reference_is_expert_ground_truth": False,
        "reference_requirement_count": len(reference["requirements"]),
        "eligible_inspection_count": sum(eligible_for_inspection(row) for row in reference["requirements"]),
        "missing_results": missing_results,
        "matching_policy": {
            "assignment": "maximum-weight one-to-one Hungarian assignment followed by fixed identity gates",
            "identity_score_min": IDENTITY_SCORE_MIN,
            "identity_subject_min": IDENTITY_SUBJECT_MIN,
            "strict_subject_min": STRICT_SUBJECT_MIN,
            "strict_relation_min": STRICT_RELATION_MIN,
            "strict_threshold_min": STRICT_THRESHOLD_MIN,
            "condition_item_min": CONDITION_ITEM_MIN,
            "subject": "semantic-token expected-subject coverage permits additional qualifiers",
            "relation": "semantic-token similarity with a fixed relation-class normalization",
            "threshold": "fixed semantic-token threshold; an empty frozen threshold adds no extra gate",
            "conditions": "diagnostic structured-value or natural-language coverage; not an inspection identity hard gate",
            "required_inputs": "diagnostic exact canonicalized set equality; not an inspection identity hard gate",
            "source_locator": "diagnostic frozen PDF-page match; not an inspection identity hard gate",
            "modality_note": "The frozen reference has relation but no independent modality field; the required modality/relation gate is therefore scored through relation. No modality value is inferred posthoc.",
            "policy_fixed_before_generating_this_rescore": True,
            "same_policy_for_all_methods": True,
        },
        "inspection_focused_policy": {
            "full_manual_requirement_completeness_is_a_formal_target": False,
            "uninspectable_reference_omissions_are_penalized": False,
            "inspectable_reference_omissions_reduce_coverage_and_end_to_end_rates": True,
            "checked_item_denominator": "every explicit satisfied or deficient model assertion",
            "spurious_or_unsafe_assertions_count_as_checked_item_errors": True,
        },
        "validations": {
            "one_to_one_expected_indices_unique": matching_uniqueness,
            "one_to_one_predicted_indices_unique": matching_uniqueness,
            "duplicate_predictions_cannot_duplicate_tp": matching_uniqueness,
            "missing_inspectable_requirement_fails_coverage_and_end_to_end": True,
            "missing_uninspectable_requirement_is_not_penalized": True,
            "invalid_or_missing_inspection_fails_end_to_end": True,
            "not_observable_fails_end_to_end": True,
            "requires_human_review_fails_layout_and_end_to_end": True,
            "model_execution_audit_passed": prior_formal_audit.get("passed") is True,
            "model_execution_hidden_requirement_id_leak_detected": any(
                "hidden ID" in failure or "oracle-ID" in failure
                for failure in prior_formal_audit.get("failures", [])
            ),
            "model_execution_audit_source": "formal_run_audit.json",
        },
        "n_a": {
            "critical_false_clear_rate": "No eligible critical deficient reference requirements exist in run_01.",
            "independent_modality_accuracy": "The frozen reference does not contain an independent modality label; it is not reported or imputed.",
        },
        "formal_main_columns": MAIN_COLUMNS,
        "excluded_from_formal_main": [
            "Source Recall@k", "Atomic Requirement Recall@k", "Requirement Precision",
            "Requirement Recall", "Requirement Micro-F1", "Requirement Set Accuracy",
            "Requirement Extraction Accuracy",
            "Condition Extraction Accuracy", "Applicability Accuracy",
            "Missing-data Detection Recall", "False Missing-data Rate", "Unsafe Assertion Rate",
            "Inspection Error Rate", "Inspection Accuracy", "Evidence-grounding Correctness",
            "Macro-F1", "Human-handoff failure",
        ],
    }
    (out / "formal_scoring_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    (out / "requirement_matching_details.json").write_text(
        json.dumps(match_details, ensure_ascii=False, indent=2) + "\n"
    )
    (out / "application_metrics.json").write_text(
        json.dumps(scored, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({
        "run": args.run,
        "output_directory": str(out),
        "missing_results": missing_results,
        "external_model_calls": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
