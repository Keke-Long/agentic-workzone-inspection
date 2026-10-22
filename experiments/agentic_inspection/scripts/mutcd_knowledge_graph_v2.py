#!/usr/bin/env python3
"""Deterministic TA/component graph queries and graph-gap retrieval."""

from __future__ import annotations

import base64
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from dense_gap_retrieval import DenseGapIndex
from inspection_registry_v5 import COVERAGE_DOMAINS
from mutcd_structure_v1 import bm25_rank
from project_common import ROOT, sha256


GRAPH_PATH = ROOT / "inputs/mutcd_knowledge_graph_v2.json"
GAP_RELATIVE_SCORE_FLOOR = 0.50
DOMAIN_GAP_QUERIES = {
    "lane_closure_layout": "temporary traffic control lane closure layout and traffic path",
    "advance_warning_sign_system": "temporary traffic control advance warning sign system",
    "channelization_system": "temporary traffic control channelization system",
    "transition_and_taper_geometry": "temporary traffic control transition and taper geometry",
    "conditional_active_devices": "temporary traffic control active devices",
    "conditional_termination_area": "temporary traffic control termination area",
}


def _has_unresolved_antecedent(node: dict, component_presence_resolves_if_used: bool = False) -> bool:
    """Conservatively detect a conditional antecedent not established by graph activation.

    This operates on grammatical condition forms rather than section numbers,
    device names, or benchmark phrases.  A component-presence trigger resolves
    only the generic ``if used`` antecedent; narrower modes/configurations remain
    review candidates.
    """
    text = str(node.get("source_span") or "").strip().casefold()
    subject = str(node.get("subject") or "").strip().casefold()
    if component_presence_resolves_if_used and re.match(r"^(if|when)\s+(used|in use)\b", text):
        return False
    if re.match(r"^(if|when|where|for|except|unless)\b", text):
        return True
    if re.search(r"\b(?:shall|should)\s+(?:be\s+used\s+)?only\b", text):
        return True
    if re.search(r"\bin\s+(?:the\s+)?[^,.;]{0,40}\bmode\b", subject):
        return True
    return False


def _token(domain: str, fingerprint: str, offset: int) -> str:
    raw = json.dumps({"domain": domain, "fingerprint": fingerprint, "offset": offset},
                     sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str | None, domain: str, fingerprint: str) -> int:
    if not value:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except Exception as exc:
        raise ValueError("invalid graph-gap continuation token") from exc
    if payload.get("domain") != domain or payload.get("fingerprint") != fingerprint:
        raise ValueError("graph-gap continuation token does not match this domain and covered set")
    return int(payload["offset"])


class MutcdKnowledgeGraphV2:
    def __init__(self, retrieval, path: Path | None = None,
                 gap_retrieval: dict | None = None) -> None:
        self.path = path or GRAPH_PATH
        self.graph = json.loads(self.path.read_text(encoding="utf-8"))
        if self.graph.get("schema_version") != "mutcd_knowledge_graph_v2":
            raise ValueError("Stage 1 graph workflow requires mutcd_knowledge_graph_v2")
        if self.graph["source_structure"]["sha256"] != sha256(retrieval.index_path):
            raise ValueError("knowledge graph was not built from the active MUTCD structure index")
        self.retrieval = retrieval
        self.gap_retrieval = gap_retrieval or {"method": "bm25"}
        self.gap_method = self.gap_retrieval.get("method", "bm25")
        self.dense_candidate_limit = int(
            self.gap_retrieval.get("candidate_limit_per_domain", 18)
        )
        self.dense_index: DenseGapIndex | None = None
        if self.gap_method == "dense_e5":
            index_path = ROOT / self.gap_retrieval["index"]
            manifest_path = ROOT / self.gap_retrieval["manifest"]
            self.dense_index = DenseGapIndex(
                index_path, manifest_path, retrieval.index_path, self.path
            )
        elif self.gap_method != "bm25":
            raise ValueError(f"unknown graph-gap retrieval method: {self.gap_method}")
        self.raw_node_by_id = {
            row["node_id"]: row for row in retrieval.index["atomic_nodes"]
        }
        self.ta_by_code = {row["source_unit_code"]: row
                           for row in self.graph["typical_applications"]}
        self.component_by_id = {row["component_id"]: row for row in self.graph["components"]}
        self.provision_by_id = {row["provision_id"]: row
                                for row in self.graph["normative_provisions"]}
        self.outgoing: dict[str, list[dict]] = defaultdict(list)
        for edge in self.graph["edges"]:
            self.outgoing[edge["from"]].append(edge)

    def _provisions_for_unit(self, source_unit_code: str) -> list[str]:
        return [edge["to"] for edge in self.outgoing.get(f"source_unit:{source_unit_code}", [])
                if edge["relation"] == "contains_normative_provision"]

    def _units_for_component(self, component_id: str) -> list[str]:
        return [edge["to"].removeprefix("source_unit:")
                for edge in self.outgoing.get(component_id, [])
                if edge["relation"] == "governed_by_source_unit"]

    def _node_view(self, provision_id: str) -> dict:
        try:
            return self.retrieval._node_view(self.raw_node_by_id[provision_id])
        except KeyError as exc:
            raise ValueError(f"knowledge-graph node is missing from the active index: {provision_id}") from exc

    @staticmethod
    def _merge_candidate(target: dict[str, dict], node: dict, domains: list[str],
                         layer: str, path: list[str], activation: dict) -> None:
        node_id = node["source_node_id"]
        if node_id not in target:
            target[node_id] = {
                "source_node": node, "domains": list(domains), "layers": [layer],
                "graph_paths": [path], "activation_evidence": [activation],
            }
            return
        row = target[node_id]
        row["domains"] = sorted(set(row["domains"]) | set(domains))
        if layer not in row["layers"]:
            row["layers"].append(layer)
        if path not in row["graph_paths"]:
            row["graph_paths"].append(path)
        if activation not in row["activation_evidence"]:
            row["activation_evidence"].append(activation)

    def ta_core(self, layout_code: str) -> dict:
        if layout_code not in self.ta_by_code:
            raise ValueError(f"unknown Typical Application in knowledge graph: {layout_code}")
        ta_id = f"ta:{layout_code}"
        candidates: dict[str, dict] = {}
        components = []
        source_units: dict[str, list[str]] = defaultdict(list)
        source_units[layout_code].append(
            f"{layout_code} -> contains numbered normative TA notes"
        )
        evidence_node_ids = []
        for node in self.retrieval.nodes_by_unit.get(layout_code, []):
            if node.get("node_type") == "figure_component":
                evidence_node_ids.append(node["node_id"])
        for edge in self.outgoing.get(ta_id, []):
            relation, target = edge["relation"], edge["to"]
            if relation.startswith("depicts_"):
                component = dict(self.component_by_id[target])
                component["depiction_relation"] = relation
                component["provenance"] = edge["provenance"]
                components.append(component)
                if relation != "depicts_optional_component":
                    for unit in self._units_for_component(target):
                        source_units[unit].append(f"{layout_code} -> {relation} -> {target}")
            elif relation in {"governed_by_source_unit", "references_source_unit"}:
                unit = target.removeprefix("source_unit:")
                # Support-only symbol tables remain graph context, not requirements.
                if unit != "TABLE-6P-2":
                    source_units[unit].append(f"{layout_code} -> {relation} -> {unit}")
        for unit, paths in source_units.items():
            for provision_id in self._provisions_for_unit(unit):
                provision = self.provision_by_id.get(provision_id)
                if not provision:
                    continue
                node = self._node_view(provision_id)
                self._merge_candidate(
                    candidates, node, provision["domains"], "stage1a_ta_core",
                    paths, {"type": "selected_ta", "layout_code": layout_code,
                            "evidence_source_node_ids": evidence_node_ids},
                )
        inferred_components: set[str] = set()
        patterns = self.graph["inference_rules"][0]["patterns"]
        for row in candidates.values():
            text = row["source_node"].get("source_span", "").lower()
            for rule in patterns:
                if rule["contains"] in text:
                    inferred_components.add(rule["target"])
            node = row["source_node"]
            direct_selected_ta = node.get("source_unit_code") == layout_code
            figure_has_normative_governor = False
            paragraph = str(node.get("paragraph") or "")
            if direct_selected_ta and paragraph.startswith("figure:sign:"):
                sign_code = paragraph.rsplit(":", 1)[-1].upper()
                match = re.match(r"^([A-Z]+\d+(?:-\d+))", sign_code)
                base_code = match.group(1) if match else sign_code
                figure_has_normative_governor = any(
                    other["source_node"].get("source_unit_code") != layout_code and
                    base_code.casefold() in str(
                        other["source_node"].get("source_span") or ""
                    ).casefold()
                    for other in candidates.values()
                )
            elif direct_selected_ta and paragraph.startswith("figure:dimension"):
                figure_has_normative_governor = any(
                    other["source_node"].get("unit_type") == "table"
                    for other in candidates.values()
                )
            explicit_referenced_table = (
                node.get("unit_type") == "table" and
                any("references_source_unit" in step
                    for path in row.get("graph_paths", []) for step in path)
            )
            direct_unconditional = (
                direct_selected_ta and not figure_has_normative_governor and
                not _has_unresolved_antecedent(node)
            )
            row["disposition_priority"] = (
                "high" if direct_unconditional or explicit_referenced_table else "review"
            )
        return {
            "layer": "stage1a_ta_core", "layout_code": layout_code,
            "ta": self.ta_by_code[layout_code], "components": components,
            "source_units": sorted(source_units), "ta_evidence_node_ids": evidence_node_ids,
            "inferred_required_component_ids": sorted(inferred_components),
            "candidates": list(candidates.values()),
        }

    @staticmethod
    def _fact_triggered(rule: dict, facts: dict) -> bool:
        value = facts.get(rule["fact_key"])
        if rule["operator"] == "is_true":
            return value is True
        if rule["operator"] == "not_null":
            return value is not None
        if rule["operator"] == "equals":
            return value == rule.get("value")
        return False

    def scene_conditions(self, scene_view: dict, inferred_component_ids: list[str]) -> dict:
        facts = scene_view.get("scene_facts", {})
        triggers = []
        component_ids = set(inferred_component_ids)
        for rule in self.graph["fact_triggers"]:
            if self._fact_triggered(rule, facts):
                triggers.append({"kind": "scene_fact", **rule, "observed_value": facts[rule["fact_key"]]})
                if rule["target"].startswith("component:"):
                    component_ids.add(rule["target"])
        class_counts = scene_view.get("accepted_observation_class_counts", {})
        for rule in self.graph["observation_triggers"]:
            count = int(class_counts.get(rule["observation_class"], 0) or 0)
            if count > 0:
                triggers.append({"kind": "observation_class", **rule, "count": count})
                component_ids.add(rule["target"])
        for component_id in inferred_component_ids:
            triggers.append({"kind": "ta_core_required_component", "target": component_id})

        candidates: dict[str, dict] = {}
        for component_id in sorted(component_ids):
            component_triggers = [row for row in triggers if row["target"] == component_id]
            for unit in self._units_for_component(component_id):
                for provision_id in self._provisions_for_unit(unit):
                    provision = self.provision_by_id.get(provision_id)
                    if not provision:
                        continue
                    node = self._node_view(provision_id)
                    self._merge_candidate(
                        candidates, node, provision["domains"], "stage1b_scene_condition",
                        [f"{component_id} -> governed_by_source_unit -> {unit}"],
                        {"type": "component_trigger", "component_id": component_id,
                         "triggers": component_triggers},
                    )
        for row in candidates.values():
            node = row["source_node"]
            row["disposition_priority"] = (
                "high" if (not node.get("scope_tags") and
                           not _has_unresolved_antecedent(
                               node, component_presence_resolves_if_used=True
                           )) else "review"
            )
        return {
            "layer": "stage1b_scene_condition", "triggers": triggers,
            "activated_component_ids": sorted(component_ids),
            "candidates": list(candidates.values()),
        }

    def gap_page(self, domain: str, covered_node_ids: set[str], page_size: int,
                 continuation_token: str | None,
                 use_domain_filter: bool = True) -> dict:
        if domain not in COVERAGE_DOMAINS:
            raise ValueError(f"unknown inspection domain: {domain}")
        page_size = min(max(int(page_size), 1), 12)
        fingerprint_input = "|".join([
            self.gap_method, str(self.dense_candidate_limit),
            str(use_domain_filter),
            *sorted(covered_node_ids),
        ])
        fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:16]
        offset = _decode(continuation_token, domain, fingerprint)
        provisions = [
            row for row in self.graph["normative_provisions"]
            if row["provision_id"] not in covered_node_ids and
            (not use_domain_filter or domain in row["domains"])
        ]
        nodes = [self._node_view(row["provision_id"]) for row in provisions]
        query = DOMAIN_GAP_QUERIES[domain]
        if self.gap_method == "bm25":
            documents = [" ".join(str(node.get(key) or "") for key in
                                  ("subject", "relation", "threshold", "source_span"))
                         for node in nodes]
            ranked = bm25_rank(query, documents)
            top_score = ranked[0][0] if ranked else 0.0
            relevance_floor = top_score * GAP_RELATIVE_SCORE_FLOOR
            positive = [(score, index) for score, index in ranked if score > 0]
            if self.gap_retrieval.get("candidate_selection") == "top_k":
                eligible = positive[:self.dense_candidate_limit]
                policy_type = "bm25_top_k"
            else:
                eligible = [
                    (score, index) for score, index in positive
                    if score >= relevance_floor
                ]
                policy_type = "relative_bm25_relevance_floor"
            ordered = [
                {**nodes[index], "gap_bm25_score": round(score, 6)}
                for score, index in eligible
            ]
            ranking_policy = {
                "type": policy_type,
                "relative_to_domain_top_score": GAP_RELATIVE_SCORE_FLOOR,
                "top_score": round(top_score, 6),
                "minimum_eligible_score": round(relevance_floor, 6),
                "zero_score_nodes_excluded": True,
                "candidate_count_cap": (
                    self.dense_candidate_limit
                    if self.gap_retrieval.get("candidate_selection") == "top_k"
                    else None
                ),
            }
        else:
            assert self.dense_index is not None
            ranked_dense = self.dense_index.rank(
                domain, [row["provision_id"] for row in provisions]
            )
            node_by_id = {node["source_node_id"]: node for node in nodes}
            selected_dense = ranked_dense[:self.dense_candidate_limit]
            ordered = [
                {**node_by_id[provision_id], "gap_dense_score": round(score, 6)}
                for score, provision_id in selected_dense
            ]
            ranking_policy = {
                "type": "dense_cosine_top_k",
                "embedding_model": self.dense_index.manifest["model_id"],
                "normalized_embeddings": True,
                "top_score": round(selected_dense[0][0], 6) if selected_dense else None,
                "minimum_eligible_score": (
                    round(selected_dense[-1][0], 6) if selected_dense else None
                ),
                "candidate_count_cap": self.dense_candidate_limit,
            }
        selected = ordered[offset:offset + page_size]
        next_offset = offset + len(selected)
        return {
            "layer": ("stage1c_graph_gap_audit" if use_domain_filter
                      else "stage1_retrieval_only"),
            "query": query, "covered_node_count": len(covered_node_ids),
            "uncovered_corpus_count": len(provisions),
            "uncovered_candidate_count": len(ordered),
            "ranking_policy": ranking_policy,
            "items": selected,
            "continuation_token": (_token(domain, fingerprint, next_offset)
                                   if next_offset < len(ordered) else None),
            "has_more": next_offset < len(ordered),
        }

    def manifest(self) -> dict[str, Any]:
        result = {"path": str(self.path), "sha256": sha256(self.path),
                  "statistics": self.graph["statistics"],
                  "build_policy": self.graph["build_policy"],
                  "stage1c_gap_retrieval": deepcopy(self.gap_retrieval)}
        if self.dense_index is not None:
            result["dense_index"] = {
                "path": str(self.dense_index.index_path),
                "sha256": sha256(self.dense_index.index_path),
                "manifest_path": str(self.dense_index.manifest_path),
                "model_id": self.dense_index.manifest["model_id"],
            }
        return result
