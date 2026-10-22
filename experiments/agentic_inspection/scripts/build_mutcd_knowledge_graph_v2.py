#!/usr/bin/env python3
"""Build a benchmark-independent semantic graph over the MUTCD structure index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from project_common import ROOT, sha256


STRUCTURE_PATH = ROOT / "inputs/mutcd_structure_v1.json"
OUTPUT_PATH = ROOT / "inputs/mutcd_knowledge_graph_v2.json"
NORMATIVE = {"shall", "standard", "should", "guidance"}


def stable_id(prefix: str, *parts: str) -> str:
    material = "|".join(parts).encode()
    return prefix + hashlib.sha256(material).hexdigest()[:20]


def provision_domains(node: dict) -> list[str]:
    code = str(node.get("source_unit_code", ""))
    region = str(node.get("region", ""))
    text = " ".join(str(node.get(key, "")) for key in
                    ("subject", "relation", "threshold")).lower()
    domains: set[str] = set()
    if code.startswith("TA-") and node.get("node_type") == "normative_clause":
        # Numbered Standard/Guidance notes on every TA page are core normative
        # content.
        domains.add("lane_closure_layout")
        if any(token in text for token in ("sign", "warning")):
            domains.add("advance_warning_sign_system")
        if "channeliz" in text or "device" in text:
            domains.add("channelization_system")
        if "taper" in text or "transition" in text:
            domains.add("transition_and_taper_geometry")
        if any(token in text for token in ("arrow board", "changeable message", "flashing")):
            domains.add("conditional_active_devices")
        if any(token in text for token in ("termination", "downstream", "end road work")):
            domains.add("conditional_termination_area")
    if (code.startswith("TA-") and node.get("node_type") == "figure_component" and
            node.get("normative_basis") and
            str(node.get("modality", "")).lower() in {"should", "guidance"}):
        # Section 6P.01 makes non-optional Typical-Application diagram content
        # Guidance. Route it by its structured figure region; do not infer from
        # a benchmark-specific sign code or expected answer.
        region_domains = {
            "advance_warning": "advance_warning_sign_system",
            "distance_table": "advance_warning_sign_system",
            "channelizing_devices": "channelization_system",
            "transition": "transition_and_taper_geometry",
            "termination": "conditional_termination_area",
        }
        if region in region_domains:
            domains.add(region_domains[region])
    # Route governing sections by their manual structure.  Incidental mention
    # of another system (for example, an active device located at a taper) does
    # not make one atomic provision belong to two inspection domains.
    if code.startswith("SEC-6N"):
        domains.add("lane_closure_layout")
    elif code.startswith("SEC-6H") or code == "TABLE-6B-1":
        domains.add("advance_warning_sign_system")
    elif code.startswith("SEC-6K"):
        domains.add("channelization_system")
    elif code.startswith("SEC-6L"):
        domains.add("conditional_active_devices")
    elif code.startswith("SEC-6B") or code in {"TABLE-6B-3", "TABLE-6B-4"}:
        domains.add("transition_and_taper_geometry")
    if region == "termination":
        domains.add("conditional_termination_area")
    return sorted(domains)


def component_from_figure(node: dict) -> dict | None:
    paragraph = str(node.get("paragraph", ""))
    if not paragraph.startswith("figure:") or paragraph == "figure:diagram":
        return None
    token = paragraph.removeprefix("figure:")
    if token.startswith("sign:"):
        code = token.split(":", 1)[1].upper()
        return {"component_id": f"component:sign:{code}", "component_type": "traffic_sign",
                "canonical_name": code, "manual_identifier": code}
    if token.startswith("dimension:L"):
        return {"component_id": "component:taper_dimension",
                "component_type": "taper_dimension",
                "canonical_name": "taper dimension", "manual_identifier": "L"}
    if token.startswith("dimensions:"):
        letters = token.split(":", 1)[1].upper()
        return {"component_id": f"component:sign_spacing_dimensions:{letters}",
                "component_type": "sign_spacing_dimension",
                "canonical_name": f"sign spacing dimensions {letters}",
                "manual_identifier": letters}
    canonical = token.replace(":", "_")
    return {"component_id": f"component:{canonical}", "component_type": "layout_or_device",
            "canonical_name": canonical.replace("_", " "), "manual_identifier": None}


def sign_base_code(code: str) -> str:
    match = re.match(r"^([A-Z]+\d+(?:-\d+))(?:[A-Z]+)?$", code.upper())
    return match.group(1) if match else code.upper()


def main() -> None:
    structure = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
    units = structure["source_units"]
    atomic = structure["atomic_nodes"]
    cross_refs = structure["cross_references"]
    unit_by_code = {row["source_unit_code"]: row for row in units}
    node_by_id = {row["node_id"]: row for row in atomic}

    provisions = []
    for node in atomic:
        if (node.get("node_type") == "figure_component" and
                (not node.get("normative_basis") or node.get("paragraph") == "figure:diagram")):
            continue
        domains = provision_domains(node)
        if str(node.get("modality", "")).lower() not in NORMATIVE or not domains:
            continue
        provisions.append({
            "provision_id": node["node_id"], "source_unit_code": node["source_unit_code"],
            "paragraph": node.get("paragraph"), "modality": node.get("modality"),
            "domains": domains, "region": node.get("region"),
        })
    provision_ids = {row["provision_id"] for row in provisions}

    tas = [{"ta_id": f"ta:{row['source_unit_code']}", "source_unit_code": row["source_unit_code"],
            "title": row["title"], "figure_code": row.get("figure_code")}
           for row in units if row.get("unit_type") == "typical_application"]
    ta_codes = {row["source_unit_code"] for row in tas}

    components: dict[str, dict] = {
        "component:arrow_board": {"component_id": "component:arrow_board",
            "component_type": "active_device", "canonical_name": "arrow board",
            "manual_identifier": None},
        "component:channelizing_device": {"component_id": "component:channelizing_device",
            "component_type": "channelizing_device", "canonical_name": "channelizing devices",
            "manual_identifier": None},
        "component:pcms": {"component_id": "component:pcms",
            "component_type": "active_device", "canonical_name": "portable changeable message sign",
            "manual_identifier": None},
    }
    edges: list[dict] = []

    def add_edge(source: str, relation: str, target: str, provenance: dict,
                 activation_role: str = "candidate") -> None:
        edge_id = stable_id("kge_", source, relation, target,
                            str(provenance.get("source_node_id") or provenance.get("edge_id") or ""))
        edges.append({"edge_id": edge_id, "from": source, "relation": relation, "to": target,
                      "activation_role": activation_role, "provenance": provenance})

    for node in atomic:
        if node["source_unit_code"] not in ta_codes or node.get("node_type") != "figure_component":
            continue
        component = component_from_figure(node)
        if not component:
            continue
        components.setdefault(component["component_id"], component)
        optional = str(node.get("modality", "")).lower() in {"may", "option"} or \
            "optional" in str(node.get("threshold", "")).lower()
        relation = "depicts_optional_component" if optional else "depicts_guidance_component"
        add_edge(f"ta:{node['source_unit_code']}", relation, component["component_id"],
                 {"kind": "figure_component", "source_node_id": node["node_id"],
                  "source_locator": node["source"]["source_locator"]},
                 "conditional" if optional else "ta_context")

    for edge in cross_refs:
        source, target = edge["from_source_unit_code"], edge["to_source_unit_code"]
        if source in ta_codes:
            relation = "references_source_unit"
            add_edge(f"ta:{source}", relation, f"source_unit:{target}",
                     {"kind": "manual_cross_reference", "edge_id": edge["edge_id"],
                      "source_span": edge["source"]["source_span"]}, "ta_context")
        if (target in ta_codes and source.startswith("SEC-6N") and
                (unit_by_code[target].get("figure_code", "") in edge["source"]["source_span"] or
                 target in edge["source"]["source_span"])):
            add_edge(f"ta:{target}", "governed_by_source_unit", f"source_unit:{source}",
                     {"kind": "manual_inbound_reference", "edge_id": edge["edge_id"],
                      "source_span": edge["source"]["source_span"]}, "ta_core")

    for provision in provisions:
        add_edge(f"source_unit:{provision['source_unit_code']}", "contains_normative_provision",
                 provision["provision_id"],
                 {"kind": "structure_index", "source_node_id": provision["provision_id"]},
                 "normative_source")

    part6_sections = [row for row in units if row["source_unit_code"].startswith("SEC-6")]
    part6_units = [row for row in units if str(row["source_unit_code"]).startswith(("SEC-6", "TABLE-6"))]
    for component in list(components.values()):
        targets: set[str] = set()
        cid = component["component_id"]
        if cid == "component:arrow_board":
            targets.update(row["source_unit_code"] for row in part6_sections
                           if "arrow board" in row["title"].lower())
        elif cid == "component:channelizing_device":
            targets.update(row["source_unit_code"] for row in part6_sections
                           if row["title"].lower().startswith("channelizing devices"))
        elif cid == "component:pcms":
            targets.update(row["source_unit_code"] for row in part6_sections
                           if "changeable message sign" in row["title"].lower())
        elif component.get("component_type") == "traffic_sign":
            base = sign_base_code(str(component.get("manual_identifier") or ""))
            targets.update(row["source_unit_code"] for row in part6_sections
                           if base and base.lower() in row["title"].lower())
            targets.update(row["source_unit_code"] for row in part6_sections
                           if "advance warning signs" in row["title"].lower())
        elif component.get("component_type") == "taper_dimension":
            targets.update(row["source_unit_code"] for row in part6_sections
                           if row["title"].strip().lower() == "tapers")
        elif component.get("component_type") == "sign_spacing_dimension":
            targets.update(row["source_unit_code"] for row in part6_units
                           if "advance warning sign" in row["title"].lower() and
                           "spacing" in row["title"].lower())
        for target in sorted(targets):
            add_edge(cid, "governed_by_source_unit", f"source_unit:{target}",
                     {"kind": "manual_identifier_or_title_match", "source_unit_code": target,
                      "matched_component": component["canonical_name"]}, "component_family")

    fact_triggers = [
        {"fact_key": "arrow_board_deployed", "operator": "is_true",
         "target": "component:arrow_board"},
        {"fact_key": "pcms_deployed", "operator": "is_true", "target": "component:pcms"},
        {"fact_key": "closed_lane", "operator": "not_null", "target": "condition:lane_closure"},
        {"fact_key": "closed_lane", "operator": "equals", "value": "left",
         "target": "condition:left_lane_closure"},
        {"fact_key": "roadway_configuration", "operator": "equals",
         "value": "multilane_undivided", "target": "condition:multilane_undivided"},
    ]
    observation_triggers = [
        {"observation_class": "channelizing_device", "target": "component:channelizing_device"},
        {"observation_class": "arrow_board", "target": "component:arrow_board"},
        {"observation_class": "pcms", "target": "component:pcms"},
    ]

    # De-duplicate deterministic edges while retaining their first provenance record.
    unique_edges = {row["edge_id"]: row for row in edges}
    graph = {
        "schema_version": "mutcd_knowledge_graph_v2",
        "manual": structure["manual"],
        "build_policy": {
            "query_independent": True, "scene_manifest_read": False,
            "hidden_reference_read": False, "benchmark_requirement_ids_present": False,
            "relationship_basis": ["manual cross-reference", "TA figure component",
                                   "TA numbered normative note", "manual identifier/title match",
                                   "manual category-title match", "6P.01 figure Guidance basis",
                                   "structure containment"],
        },
        "source_structure": {"path": str(STRUCTURE_PATH), "sha256": sha256(STRUCTURE_PATH)},
        "typical_applications": sorted(tas, key=lambda row: int(row["source_unit_code"].split("-")[1])),
        "components": sorted(components.values(), key=lambda row: row["component_id"]),
        "normative_provisions": sorted(provisions, key=lambda row: row["provision_id"]),
        "edges": sorted(unique_edges.values(), key=lambda row: row["edge_id"]),
        "fact_triggers": fact_triggers,
        "observation_triggers": observation_triggers,
        "inference_rules": [{
            "rule_id": "required-component-from-core-provision-v1",
            "description": "A TA-core provision whose source text requires a known device family activates that component family as a conditional candidate source.",
            "patterns": [
                {"contains": "channelizing device", "target": "component:channelizing_device"},
            ],
        }],
        "statistics": {
            "typical_application_count": len(tas), "component_count": len(components),
            "normative_provision_count": len(provisions), "edge_count": len(unique_edges),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT_PATH), **graph["statistics"]}, indent=2))


if __name__ == "__main__":
    main()
