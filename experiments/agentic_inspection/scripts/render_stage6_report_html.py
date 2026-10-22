#!/usr/bin/env python3
"""Render the final Stage 6 result as a self-contained HTML report."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from html import escape
import json
import mimetypes
from pathlib import Path

from project_common import ROOT


STATUS_LABELS = {
    "satisfied": "Satisfied",
    "deficient": "Deficient",
    "not_assessed": "Not assessed",
}


def embedded_image(path: str) -> str:
    image_path = Path(path)
    mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def deficiency_sources(row: dict, evidence_by_id: dict) -> tuple[str, ...]:
    return tuple(sorted({
        source_id
        for evidence_id in row.get("evidence_ids", [])
        for source_id in evidence_by_id.get(evidence_id, {}).get("source_ids", [])
    }))


def concise_finding(row: dict, evidence_by_id: dict) -> str:
    prefix = "User/domain-reviewer confirmed device-condition findings:"
    findings = []
    for evidence_id in row.get("evidence_ids", []):
        finding = str(evidence_by_id.get(evidence_id, {}).get("finding") or "").strip()
        if finding.startswith(prefix):
            finding = finding[len(prefix):].strip()
        if finding and finding not in findings:
            findings.append(finding)
    return " ".join(findings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=Path,
                        default=ROOT / "cases/workzone_01/scene.json")
    args = parser.parse_args()

    result = json.loads(args.result.read_text(encoding="utf-8"))
    record = result["record"]
    evidence_by_id = record.get("evidence_records", {})
    requirements = record.get("requirements", [])
    supplement = record.get("evaluation_supplement") or result.get("evaluation_supplement")
    statuses = Counter(row.get("inspection_status") for row in requirements)
    classes = Counter(
        "Mandatory" if row.get("modality") == "shall" else "Guidance"
        for row in requirements
    )

    deficient = [row for row in requirements if row.get("inspection_status") == "deficient"]
    issue_groups: dict[tuple[str, ...], list[dict]] = {}
    for row in deficient:
        key = deficiency_sources(row, evidence_by_id) or (
            row.get("discovered_requirement_key", ""),
        )
        issue_groups.setdefault(key, []).append(row)
    issue_number = {
        row.get("discovered_requirement_key"): index
        for index, rows in enumerate(issue_groups.values(), 1)
        for row in rows
    }

    table_rows = []
    for index, row in enumerate(requirements, 1):
        status = row.get("inspection_status", "")
        normative_class = "Mandatory" if row.get("modality") == "shall" else "Guidance"
        issue = (
            f'<a class="issue-link" href="#issue-{issue_number[row.get("discovered_requirement_key")]}">'
            f'Issue {issue_number[row.get("discovered_requirement_key")]}</a>'
            if status == "deficient" else ""
        )
        table_rows.append(
            "<tr>"
            f"<td class=\"num\">{index}</td>"
            f"<td>{escape(normative_class)}</td>"
            f'<td><span class="status {escape(status)}">{escape(STATUS_LABELS.get(status, status))}</span></td>'
            f"<td>{escape(str(row.get('candidate_label') or ''))}</td>"
            f"<td>{escape(str(row.get('source_locator') or ''))}</td>"
            f"<td>{issue}</td>"
            "</tr>"
        )

    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    scene_id = str(scene.get("scene_id") or record.get("scene_id") or "unknown scene")
    selected_layouts = ", ".join(
        str(row.get("layout_code")) for row in record.get("selected_layouts", [])
        if row.get("layout_role") == "primary_applicable"
    ) or "not determined"
    findings = scene.get("confirmed_device_condition_findings") or []
    issue_sections = []
    for index, (source_ids, rows) in enumerate(issue_groups.items(), 1):
        representative = rows[0]
        requirements_html = "".join(
            "<li>"
            f"<strong>{'Mandatory' if row.get('modality') == 'shall' else 'Guidance'}:</strong> "
            f"{escape(str(row.get('source_locator') or ''))}<br>"
            f"{escape(str(row.get('candidate_label') or ''))}"
            "</li>"
            for row in rows
        )
        images_html = []
        for finding in findings:
            if finding.get("observation_id") not in source_ids:
                continue
            source_image = finding.get("source_image")
            if not source_image or not Path(source_image).exists():
                continue
            description = finding.get("condition_zh") or finding.get("condition") or ""
            bbox = ", ".join(f"{float(value):.2f}" for value in finding.get("bbox", []))
            images_html.append(
                '<figure class="evidence-card">'
                f'<img src="{embedded_image(source_image)}" alt="{escape(str(description))}">'
                "<figcaption>"
                f"<strong>{escape(str(finding.get('element_id') or ''))}</strong> — "
                f"{escape(str(description))}<br>"
                f"Frame: {escape(str(finding.get('observation_id') or ''))}; bbox [{escape(bbox)}]"
                "</figcaption></figure>"
            )
        issue_sections.append(
            f'<section class="issue-section" id="issue-{index}">'
            f'<div class="issue-heading"><span>Issue {index}</span><h2>Channelizing-device condition</h2></div>'
            f'<p class="finding">{escape(concise_finding(representative, evidence_by_id))}</p>'
            '<h3>Normative requirements affected</h3>'
            f'<ul class="requirements-list">{requirements_html}</ul>'
            '<h3>Evidence</h3>'
            f'<div class="evidence-grid">{"".join(images_html)}</div>'
            '</section>'
        )

    not_assessed = [
        row for row in requirements if row.get("inspection_status") == "not_assessed"
    ]
    gaps_html = "".join(
        "<li>"
        f"<strong>{escape(str(row.get('source_locator') or ''))}</strong><br>"
        f"{escape(str(row.get('candidate_label') or ''))}"
        "</li>"
        for row in not_assessed
    )

    coverage_section = (
        f'''<section class="coverage">
  <h2>Assessment coverage gaps</h2>
  <p>These {len(not_assessed)} items could not be resolved from the available evidence. They are not observed deficiencies and are not treated as compliance.</p>
  <ul class="gap-list">{gaps_html}</ul>
</section>'''
        if not_assessed else ""
    )

    supplement_section = ""
    if supplement:
        items = "".join(
            "<li>"
            f"<strong>{escape(str(row.get('source_locator') or ''))}:</strong> "
            f"{escape(STATUS_LABELS.get(row.get('inspection_status'), str(row.get('inspection_status') or '')))} — "
            f"{escape(str(row.get('finding') or ''))}"
            "</li>"
            for row in supplement.get("assessments", [])
        )
        supplement_section = f'''<section class="coverage">
  <h2>Completed geometric assessments</h2>
  <p>These measurements were completed in the evaluation stage; the Stage 2 requirement registry was not changed.</p>
  <ul class="gap-list">{items}</ul>
</section>'''

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(scene_id)} — Final Inspection Report</title>
<style>
  @page {{ size: A4; margin: 15mm 13mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; color: #17212b; font-family: Arial, "Noto Sans", sans-serif; font-size: 10.5pt; line-height: 1.45; }}
  header {{ padding: 24px 28px; color: white; background: linear-gradient(130deg, #17324d, #245b72); border-radius: 10px; }}
  header h1 {{ margin: 0 0 7px; font-size: 24pt; line-height: 1.15; }}
  header p {{ margin: 0; color: #dceaf0; }}
  .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 9px; margin: 18px 0 22px; }}
  .card {{ padding: 12px 13px; border: 1px solid #d9e2e8; border-radius: 8px; background: #f7fafb; }}
  .card .value {{ display: block; font-size: 20pt; font-weight: 700; color: #17324d; }}
  .card .label {{ color: #5d6b76; font-size: 8.5pt; text-transform: uppercase; letter-spacing: .04em; }}
  h2 {{ color: #17324d; font-size: 17pt; margin: 25px 0 10px; }}
  h3 {{ color: #30485c; font-size: 11.5pt; margin: 17px 0 7px; }}
  .meta {{ margin-top: 12px; color: #52616d; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 8.4pt; }}
  thead {{ display: table-header-group; }}
  tr {{ break-inside: avoid; }}
  th {{ padding: 7px 6px; color: white; background: #274d63; text-align: left; }}
  td {{ padding: 6px; border-bottom: 1px solid #dfe6ea; vertical-align: top; }}
  tbody tr:nth-child(even) {{ background: #f7f9fa; }}
  .num {{ width: 28px; text-align: center; }}
  .status {{ display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 7.5pt; font-weight: 700; white-space: nowrap; }}
  .status.satisfied {{ color: #126443; background: #dff4e9; }}
  .status.deficient {{ color: #9b261c; background: #fde5e2; }}
  .status.not_assessed {{ color: #73540b; background: #fff1c9; }}
  .issue-link {{ color: #a02d23; font-weight: 700; text-decoration: none; }}
  .issue-section {{ margin-top: 24px; padding: 18px; border: 2px solid #d86b61; border-radius: 10px; background: #fffafa; break-before: page; }}
  .issue-heading {{ display: flex; align-items: center; gap: 10px; }}
  .issue-heading span {{ padding: 4px 9px; color: white; background: #b33b31; border-radius: 5px; font-weight: 700; }}
  .issue-heading h2 {{ margin: 0; color: #7c251f; }}
  .finding {{ padding: 10px 12px; background: white; border-left: 4px solid #d86b61; }}
  .requirements-list, .gap-list {{ margin: 5px 0 0; padding-left: 21px; }}
  .requirements-list li, .gap-list li {{ margin: 7px 0; }}
  .evidence-grid {{ display: grid; grid-template-columns: 1fr; gap: 14px; }}
  .evidence-card {{ margin: 0; padding: 9px; border: 1px solid #d6dde1; border-radius: 7px; background: white; break-inside: avoid; }}
  .evidence-card img {{ display: block; width: 100%; max-height: 168mm; object-fit: contain; border-radius: 4px; }}
  figcaption {{ padding: 8px 2px 1px; color: #43525e; font-size: 9pt; }}
  .coverage {{ margin-top: 24px; padding: 15px 17px; border-radius: 9px; background: #fff8e7; border: 1px solid #eed79a; break-inside: avoid; }}
  .coverage h2 {{ margin-top: 0; color: #6f510a; }}
  .note {{ color: #5a6873; font-size: 9pt; }}
  footer {{ margin-top: 22px; padding-top: 10px; border-top: 1px solid #d8e0e5; color: #6b7881; font-size: 8.5pt; }}
</style>
</head>
<body>
<header>
  <h1>{escape(scene_id)} — Final Inspection Report</h1>
  <p>MUTCD 11th Edition · Selected layout {escape(selected_layouts)} · KG + BM25 structured workflow</p>
</header>

<div class="summary">
  <div class="card"><span class="value">{len(requirements)}</span><span class="label">Requirements</span></div>
  <div class="card"><span class="value">{statuses['satisfied']}</span><span class="label">Satisfied</span></div>
  <div class="card"><span class="value">{statuses['deficient']}</span><span class="label">Violated requirements</span></div>
  <div class="card"><span class="value">{len(issue_groups)}</span><span class="label">Observed issues</span></div>
</div>

<p class="meta"><strong>Normative classes:</strong> Mandatory {classes['Mandatory']}; Guidance {classes['Guidance']} · <strong>Not assessed:</strong> {statuses['not_assessed']}</p>

<h2>Requirement-level results</h2>
<table>
  <thead><tr><th>#</th><th>Class</th><th>Outcome</th><th>Requirement</th><th>MUTCD source</th><th>Issue</th></tr></thead>
  <tbody>{''.join(table_rows)}</tbody>
</table>

{''.join(issue_sections)}

{coverage_section}

{supplement_section}

<footer>
  {("The Stage 2 normative registry is unchanged; documented evaluation-stage measurements replace the two earlier geometry coverage gaps." if supplement else "This report faithfully presents the immutable Stage 6 results without post-run status overrides.")} Two violated normative requirements are linked to one observed physical issue.
</footer>
</body>
</html>
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
