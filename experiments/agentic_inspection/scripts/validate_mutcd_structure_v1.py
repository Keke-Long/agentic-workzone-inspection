#!/usr/bin/env python3
"""Offline structural QA for the query-independent MUTCD index."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from project_common import ROOT, sha256
from srag_bm25_retrieval_v5 import StructuredBM25V5


INTERNAL_ID = re.compile(r"\bL\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+)+\b")


def main() -> None:
    retrieval = StructuredBM25V5()
    index = retrieval.index
    checks: list[dict] = []

    def add(name: str, passed: bool, evidence) -> None:
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    units = index["source_units"]
    nodes = index["atomic_nodes"]
    unit_codes = {row["source_unit_code"] for row in units}
    node_ids = [row["node_id"] for row in nodes]
    add("manual build is query-independent and ID-free",
        index["build_policy"]["query_independent"] is True and
        index["build_policy"]["scene_manifest_read"] is False and
        index["build_policy"]["hidden_reference_read"] is False and
        not INTERNAL_ID.search(json.dumps(index, ensure_ascii=False)), index["build_policy"])
    add("every source hash is unique", len(node_ids) == len(set(node_ids)),
        {"node_count": len(node_ids), "unique_node_count": len(set(node_ids))})
    add("all 54 Typical Applications have a diagram node",
        all(any(row["node_type"] == "figure_component" and row["paragraph"] == "figure:diagram"
                for row in retrieval.nodes_by_unit.get(f"TA-{number}", [])) for number in range(1, 55)),
        {"typical_application_count": sum(row["unit_type"] == "typical_application" for row in units),
         "diagram_node_count": sum(row["node_type"] == "figure_component" and
                                   row["paragraph"] == "figure:diagram" for row in nodes)})
    diagram_nodes = [row for row in nodes if row["node_type"] == "figure_component" and
                     row["paragraph"] == "figure:diagram"]
    missing_images = [row["source_unit_code"] for row in diagram_nodes
                      if not row["source"].get("figure_image_path") or
                      not Path(row["source"].get("figure_image_path", "")).is_file()]
    add("all Typical Application diagrams have frozen source-page images",
        len(diagram_nodes) == 54 and not missing_images,
        {"diagram_nodes": len(diagram_nodes), "missing_images": missing_images})
    required_tables = {"TABLE-6B-1", "TABLE-6B-3", "TABLE-6B-4", "TABLE-6P-2"}
    add("diagram reference tables are first-class source units",
        required_tables <= unit_codes and all(retrieval.nodes_by_unit.get(code) for code in required_tables),
        {"required": sorted(required_tables), "present": sorted(required_tables & unit_codes)})
    expected_top = {
        "Table 6P-2 meanings of symbols used in Typical Application diagrams": "TABLE-6P-2",
        "Table 6B-1 letter codes A B C warning sign spacing": "TABLE-6B-1",
        "Table 6B-4 taper length formula": "TABLE-6B-4",
        "channelizing device spacing taper tangent S 2S": "SEC-6K.01",
    }
    ranks = {query: retrieval.search_manual(query, 1)["items"][0]["source_unit_code"]
             for query in expected_top}
    add("manual-native table and rule queries rank the correct source first",
        all(ranks[query] == code for query, code in expected_top.items()),
        {"expected": expected_top, "actual": ranks})
    ta30 = retrieval.nodes_by_unit["TA-30"]
    components = {row["paragraph"] for row in ta30 if row["node_type"] == "figure_component"}
    expected_components = {
        "figure:diagram", "figure:sign:W20-1", "figure:sign:W20-5L", "figure:sign:W4-2L",
        "figure:dimensions:A-B-C", "figure:dimension:L", "figure:buffer_space",
        "figure:truck_mounted_attenuator", "figure:work_vehicle",
    }
    add("TA-30 exposes its machine-readable diagram components",
        expected_components <= components,
        {"expected": sorted(expected_components), "actual": sorted(components)})
    ta30_targets = {row["to_source_unit_code"] for row in retrieval.follow_cross_reference("TA-30")["items"]}
    add("TA-30 graph reaches its explicitly referenced tables",
        {"TABLE-6B-1", "TABLE-6B-4", "TABLE-6P-2"} <= ta30_targets,
        {"targets": sorted(ta30_targets)})
    source_failures = []
    for row in nodes:
        source = row.get("source", {})
        if not source.get("pdf_page") or not source.get("source_locator") or not source.get("source_span"):
            source_failures.append(row["node_id"])
    add("every atomic node has page locator and nonempty source span", not source_failures,
        {"failure_count": len(source_failures), "examples": source_failures[:10]})
    node_types = Counter(row["node_type"] for row in nodes)
    report = {
        "schema": "mutcd_structure_v1_validation_v1",
        "passed": all(row["passed"] for row in checks),
        "index_path": str(retrieval.index_path), "index_sha256": sha256(retrieval.index_path),
        "source_unit_count": len(units), "atomic_node_count": len(nodes),
        "cross_reference_count": len(index["cross_references"]),
        "node_type_counts": dict(sorted(node_types.items())), "checks": checks,
    }
    output = ROOT / "inputs/mutcd_structure_v1_validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks),
                      "output": str(output)}, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
