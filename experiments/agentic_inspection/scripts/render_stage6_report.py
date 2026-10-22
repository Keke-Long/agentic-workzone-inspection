#!/usr/bin/env python3
"""Render the finalized autonomous inspection registry as a concise report."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from project_common import ROOT


def compact(text: object) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def not_assessed_group(row: dict) -> str:
    """Group evidence gaps by inspection need, without requirement-specific rules."""
    measurement_spec = row.get("measurement_spec") or {}
    if measurement_spec.get("required") or row.get("unresolved_inputs"):
        return "Numerical distance or geometry could not be validated"
    region = row.get("region")
    if region == "advance_warning_sign_system":
        return "Sign identity, position, or approach sequence was not fully resolved"
    if region == "conditional_active_devices":
        return "Active-device mode, placement, or surrounding context was not fully resolved"
    return "The available field view did not fully resolve the layout predicate"


def load_confirmed_findings(scene_path: Path) -> list[dict]:
    if not scene_path.exists():
        return []
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    return list(scene.get("confirmed_device_condition_findings") or [])


def deficiency_issue(row: dict, evidence_by_id: dict) -> str:
    """Prefer the concise structured finding over a model's longer rationale."""
    findings = []
    prefix = "User/domain-reviewer confirmed device-condition findings:"
    for evidence_id in row.get("evidence_ids", []):
        finding = compact(evidence_by_id.get(evidence_id, {}).get("finding"))
        if finding.startswith(prefix):
            finding = finding[len(prefix):].strip()
        if finding and finding not in findings:
            findings.append(finding)
    if findings:
        return " ".join(findings)
    reason = compact(row.get("inspection_reason"))
    return reason.split(". ", 1)[0].rstrip(".") + "." if reason else ""


def group_deficiencies(rows: list[dict], evidence_by_id: dict) -> list[dict]:
    """Collapse normative violations supported by the same observed condition."""
    grouped: dict[tuple[str, ...], dict] = {}
    for row in rows:
        source_ids = sorted({
            source_id
            for evidence_id in row.get("evidence_ids", [])
            for source_id in evidence_by_id.get(evidence_id, {}).get("source_ids", [])
        })
        key = tuple(source_ids) or (row.get("discovered_requirement_key", ""),)
        group = grouped.setdefault(key, {"source_ids": source_ids, "rows": []})
        group["rows"].append(row)
    return list(grouped.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=Path,
                        default=ROOT / "cases/workzone_01/scene.json")
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    scene = json.loads(args.scene.read_text())
    record = result["record"]
    requirements = record.get("requirements", [])
    evidence_by_id = record.get("evidence_records", {})
    status_counts = Counter(row.get("inspection_status") for row in requirements)
    class_counts = Counter(
        "Mandatory" if row.get("modality") == "shall" else "Guidance"
        for row in requirements
    )
    deficient_rows = [
        row for row in requirements if row.get("inspection_status") == "deficient"
    ]
    deficiency_groups = group_deficiencies(deficient_rows, evidence_by_id)
    issue_number_by_key = {
        row.get("discovered_requirement_key"): issue_number
        for issue_number, group in enumerate(deficiency_groups, 1)
        for row in group["rows"]
    }
    not_assessed_rows = [
        row for row in requirements if row.get("inspection_status") == "not_assessed"
    ]
    supplement = record.get("evaluation_supplement") or result.get("evaluation_supplement")
    scene_id = str(scene.get("scene_id") or record.get("scene_id") or "unknown scene")
    selected_layouts = ", ".join(
        str(row.get("layout_code")) for row in record.get("selected_layouts", [])
        if row.get("layout_role") == "primary_applicable"
    ) or "not determined"
    lines = [
        f"# {scene_id} — Stage 6 Final Inspection Report",
        "",
        f"- Method: `{result.get('method_id')}` (KG + BM25, structured Stage 2)",
        f"- Selected MUTCD layout: `{selected_layouts}`",
        f"- Finalized requirements: {len(requirements)}",
        f"- Normative classes: Mandatory {class_counts['Mandatory']}; Guidance {class_counts['Guidance']}",
        f"- Outcomes: satisfied {status_counts['satisfied']}; deficient {status_counts['deficient']}; not_assessed {status_counts['not_assessed']}",
        f"- Unique observed issues: {len(deficiency_groups)}",
        "",
        "The `req_...` values are run-local traceability keys, not MUTCD identifiers. "
        "The authoritative citation for each row is the MUTCD source locator.",
        "",
        "| # | Class | Outcome | Requirement | MUTCD source | Issue |",
        "|---:|---|---|---|---|---|",
    ]
    for index, row in enumerate(requirements, 1):
        normative_class = "Mandatory" if row.get("modality") == "shall" else "Guidance"
        issue = (
            f"[Issue {issue_number_by_key[row.get('discovered_requirement_key')]}]"
            f"(#issue-{issue_number_by_key[row.get('discovered_requirement_key')]}--channelizing-device-condition)"
            if row.get("inspection_status") == "deficient"
            else ""
        )
        lines.append(
            f"| {index} | {normative_class} | `{compact(row.get('inspection_status'))}` | "
            f"{compact(row.get('candidate_label'))} (`{row.get('discovered_requirement_key')}`) | "
            f"{compact(row.get('source_locator'))} | {issue} |"
        )
    if deficient_rows:
        lines.extend(["", "## Confirmed issues", ""])
        confirmed_findings = load_confirmed_findings(args.scene)
        for issue_number, group in enumerate(deficiency_groups, 1):
            representative = group["rows"][0]
            lines.extend([
                f"### Issue {issue_number} — Channelizing-device condition",
                "",
                deficiency_issue(representative, evidence_by_id),
                "",
                "Normative requirements affected:",
                "",
            ])
            for row in group["rows"]:
                normative_class = (
                    "Mandatory" if row.get("modality") == "shall" else "Guidance"
                )
                lines.append(
                    f"- **{normative_class}:** {compact(row.get('source_locator'))} — "
                    f"{compact(row.get('candidate_label'))}."
                )
            lines.extend([
                "",
                "Evidence sources: "
                + ", ".join(f"`{value}`" for value in group["source_ids"])
                + ".",
            ])
            matching_findings = [
                finding for finding in confirmed_findings
                if finding.get("observation_id") in group["source_ids"]
            ]
            if matching_findings:
                lines.extend(["", "#### Evidence images", ""])
            for finding in matching_findings:
                source_image = finding.get("source_image")
                if not source_image or not Path(source_image).exists():
                    continue
                bbox = finding.get("bbox") or []
                bbox_text = ", ".join(f"{float(value):.2f}" for value in bbox)
                label = compact(finding.get("element_id"))
                observation_id = compact(finding.get("observation_id"))
                description = compact(
                    finding.get("condition_zh") or finding.get("condition")
                )
                lines.extend(
                    [
                        f"##### {label} — {description}",
                        "",
                        f"Evidence frame `{observation_id}`; bounding box `[{bbox_text}]`.",
                        "",
                        f"![Evidence {label} — {description}]({source_image})",
                        "",
                    ]
                )
    if not_assessed_rows:
        gap_counts = Counter(not_assessed_group(row) for row in not_assessed_rows)
        lines.extend(
            [
                "",
                "## Assessment coverage gaps",
                "",
                "These are evidence or measurement gaps, not observed deficiencies:",
                "",
            ]
        )
        for group, count in gap_counts.items():
            lines.append(f"- {count}: {group}.")
    if supplement:
        lines.extend([
            "",
            "## Completed geometric assessments",
            "",
            "These measurements were completed in the evaluation stage; the Stage 2 requirement registry was not changed.",
            "",
        ])
        for assessment in supplement.get("assessments", []):
            lines.append(
                f"- **{compact(assessment.get('source_locator'))}:** "
                f"`{compact(assessment.get('inspection_status'))}` — "
                f"{compact(assessment.get('finding'))}"
            )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "`not_assessed` means the registered requirement remained applicable but the bound evidence "
        "did not support a definitive satisfied/deficient decision. It is reported as a coverage gap, "
        "not as a work-zone problem and not as compliance.",
        "",
        "## Completion",
        "",
        (f"This report presents all {len(requirements)} registered requirements. "
         "The Stage 2 normative registry is unchanged; documented evaluation-stage measurements "
         "replace the two earlier geometry coverage gaps." if supplement else
         f"This report is a faithful presentation of all {len(requirements)} immutable Stage 6 results. "
         "No post-run status override, applicability deletion, or requirement consolidation is applied."),
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
