#!/usr/bin/env python3
"""Evaluate Stage 1 retrieval independently of Stage 2 registration.

The fixed checklist is evaluator-only. A requirement is retrieved only when all
of its cited atomic section paragraphs/tables were surfaced as source nodes.
Search-result unit titles alone do not count; the source unit must be expanded.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re
from pathlib import Path

from project_common import ROOT


DEFAULT_CHECKLIST = ROOT / "ground_truth/workzone_fixed_coverage_checklist.json"


def _source_atoms(source: str) -> list[tuple[str, str | None]]:
    table = re.search(r"\bTable\s+(6[A-Z]-\d+)\b", source, re.I)
    if table:
        return [(f"TABLE-{table.group(1).upper()}", None)]
    section = re.search(r"\b(6[A-Z]\.[0-9]{2})\b", source, re.I)
    if not section:
        return []
    code = f"SEC-{section.group(1).upper()}"
    suffix = source[section.end():]
    if not re.search(r"\bparagraphs?\b", suffix, re.I):
        return [(code, None)]
    numbers = re.findall(r"\b([0-9]{1,2})\b", suffix)
    return [(code, value.zfill(2)) for value in numbers]


def _retrieved_atoms(trace: list[dict]) -> set[tuple[str, str | None]]:
    atoms: set[tuple[str, str | None]] = set()
    node_tools = {"search_manual_for_need", "expand_source_unit", "expand_source_unit_for_need",
                  "follow_cross_reference", "read_source_node", "load_ta_core_graph",
                  "load_scene_condition_graph", "audit_graph_gaps",
                  "load_domain_gap_candidates"}
    for event in trace:
        if event.get("tool") not in node_tools:
            continue
        result = event.get("result", {})
        for item in (result.get("items", []) + result.get("atomic_items", []) +
                     result.get("candidates", [])):
            code = item.get("source_unit_code")
            if not code or not item.get("source_node_id"):
                continue
            paragraph = item.get("paragraph")
            atoms.add((code.upper(), str(paragraph).zfill(2) if paragraph is not None else None))
            atoms.add((code.upper(), None))
    return atoms


def evaluate(trace_path: Path, checklist_path: Path) -> dict:
    trace = json.loads(trace_path.read_text())
    checklist = json.loads(checklist_path.read_text())
    expected_ids = checklist["stage1_stage2_test_profile"]["expected_activated_requirement_ids"]
    by_id = {row["id"]: row for row in checklist["requirements"]}
    retrieved = _retrieved_atoms(trace)
    rows = []
    domain_totals: dict[str, list[bool]] = defaultdict(list)
    atom_total = atom_hit = 0
    for requirement_id in expected_ids:
        requirement = by_id[requirement_id]
        atoms = [atom for source in requirement["mutcd_sources"] for atom in _source_atoms(source)]
        missing = [atom for atom in atoms if atom not in retrieved]
        hit = bool(atoms) and not missing
        atom_total += len(atoms)
        atom_hit += len(atoms) - len(missing)
        domain_totals[requirement["domain"]].append(hit)
        rows.append({
            "requirement_id": requirement_id,
            "domain": requirement["domain"],
            "normative_level": requirement["normative_level"],
            "expected_source_atoms": [{"source_unit_code": code, "paragraph": paragraph}
                                      for code, paragraph in atoms],
            "missing_source_atoms": [{"source_unit_code": code, "paragraph": paragraph}
                                     for code, paragraph in missing],
            "retrieved": hit,
        })
    hits = sum(row["retrieved"] for row in rows)
    return {
        "schema_version": "stage1_retrieval_six_domain_evaluation_v1",
        "profile_id": checklist["stage1_stage2_test_profile"]["profile_id"],
        "requirement_count": len(rows),
        "retrieved_requirement_count": hits,
        "requirement_recall": hits / len(rows) if rows else 1.0,
        "source_atom_count": atom_total,
        "retrieved_source_atom_count": atom_hit,
        "source_atom_recall": atom_hit / atom_total if atom_total else 1.0,
        "majority_target": 0.8,
        "majority_target_met": (hits / len(rows) if rows else 1.0) >= 0.8,
        "domains": {
            domain: {"expected": len(values), "retrieved": sum(values),
                     "recall": sum(values) / len(values)}
            for domain, values in domain_totals.items()
        },
        "missed_requirement_ids": [row["requirement_id"] for row in rows if not row["retrieved"]],
        "requirements": rows,
        "note": "Posthoc evaluator only; checklist IDs, expected sources, and target counts are never exposed to the agent.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.trace, args.checklist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
