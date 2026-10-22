#!/usr/bin/env python3
"""Paged BM25 access to the query-independent MUTCD structure index.

The retriever never reads a scene reference or requirement catalog. All
identifiers exposed to the model are MUTCD-native source-unit codes or hashes
derived from manual text.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from mutcd_structure_v1 import bm25_rank
from project_common import ROOT


def _token(kind: str, key: str, offset: int) -> str:
    payload = json.dumps({"kind": kind, "key": key, "offset": offset}, sort_keys=True).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode(value: str | None, kind: str, key: str) -> int:
    if not value:
        return 0
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        parsed = json.loads(raw)
    except Exception as exc:
        raise ValueError("invalid continuation token") from exc
    if parsed != {"kind": kind, "key": key, "offset": parsed.get("offset")}:
        raise ValueError("continuation token does not belong to this query")
    return int(parsed["offset"])


def _normalized_source_code(value: str) -> str:
    normalized = value.strip().upper().replace("SECTION ", "SEC-").replace(" ", "")
    if re.fullmatch(r"\d+[A-Z]\.\d{2}", normalized):
        return "SEC-" + normalized
    if re.fullmatch(r"TA-?\d{1,3}", normalized):
        return "TA-" + str(int(re.search(r"\d+", normalized).group()))
    if re.fullmatch(r"TABLE-?\d+[A-Z]-?\d+", normalized):
        match = re.fullmatch(r"TABLE-?(\d+[A-Z])-?(\d+)", normalized)
        return f"TABLE-{match.group(1)}-{int(match.group(2))}"
    return normalized


class StructuredBM25V5:
    """Full-corpus structured MUTCD retrieval with per-response paging."""

    def __init__(self, index_path: Path | None = None, max_items_per_response: int = 12) -> None:
        path = index_path or ROOT / "inputs/mutcd_structure_v1.json"
        self.index_path = path
        self.index = json.loads(path.read_text(encoding="utf-8"))
        if self.index.get("schema_version") != "mutcd_structure_v1":
            raise ValueError("S-RAG-BM25 v5 requires the MUTCD v1 structure index")
        self.units = self.index["source_units"]
        self.nodes = self.index["atomic_nodes"]
        self.unit_by_code = {row["source_unit_code"]: row for row in self.units}
        self.nodes_by_unit: dict[str, list[dict]] = {}
        for node in self.nodes:
            self.nodes_by_unit.setdefault(node["source_unit_code"], []).append(node)
        self.edges_by_source: dict[str, list[dict]] = {}
        for edge in self.index["cross_references"]:
            self.edges_by_source.setdefault(edge["from_source_unit_code"], []).append(edge)
        self.max_items_per_response = max_items_per_response
        self.resources = {
            "regulation_retrieval_calls": 0, "retrieval_queries": [],
            "retrieved_chunks_nodes": 0, "retrieved_characters": 0,
        }

    def _unit_document(self, row: dict) -> str:
        clauses = self.nodes_by_unit.get(row["source_unit_code"], [])
        return " ".join(filter(None, [
            row["source_unit_code"], row.get("unit_type"), row.get("chapter"), row.get("title"),
            " ".join(row.get("available_regions", [])), row.get("raw_text"),
            " ".join(context.get("source_span", "") for context in row.get("inbound_reference_contexts", [])),
            " ".join(" ".join(str(node.get(key, "")) for key in
                              ("subject", "relation", "threshold", "source")) for node in clauses),
        ]))

    @staticmethod
    def _node_view(node: dict) -> dict:
        source = node["source"]
        view = {
            "source_node_id": node["node_id"], "source_unit_code": node["source_unit_code"],
            "unit_type": node["unit_type"], "chapter": node.get("chapter"),
            "region": node["region"], "node_type": node["node_type"],
            "paragraph": node.get("paragraph"), "subject": node["subject"],
            "modality": node["modality"], "relation": node["relation"],
            "threshold": node["threshold"],
            "applicability_conditions": node["applicability_conditions"],
            "required_inputs": node["required_inputs"],
            "scope_tags": node.get("scope_tags", []),
            "source_locator": source["source_locator"], "pdf_page": source["pdf_page"],
            "printed_page": source.get("printed_page"), "source_span": source["source_span"],
        }
        if node.get("normative_basis"):
            view["normative_basis"] = node["normative_basis"]
        if source.get("figure_image_path"):
            view["figure_image_path"] = source["figure_image_path"]
        return view

    def _record(self, operation: str, query: str, result: dict) -> dict:
        self.resources["regulation_retrieval_calls"] += 1
        self.resources["retrieval_queries"].append({"operation": operation, "query": query})
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        self.resources["retrieved_characters"] += len(payload)
        self.resources["retrieved_chunks_nodes"] += len(result.get("items", []))
        return result

    def search_manual(self, query: str, page_size: int = 10,
                      continuation_token: str | None = None) -> dict:
        if not query.strip():
            raise ValueError("query must be non-empty natural language")
        page_size = min(max(int(page_size), 1), self.max_items_per_response)
        key = hashlib.sha256(query.strip().encode()).hexdigest()
        offset = _decode(continuation_token, "search", key)
        ranked = bm25_rank(query, [self._unit_document(row) for row in self.units])
        query_upper = query.upper().replace(" ", "")
        exact_codes = set()
        exact_codes.update(f"TA-{int(value)}" for value in re.findall(r"TA-?(\d{1,3})", query_upper))
        exact_codes.update(f"SEC-{value}" for value in re.findall(r"(?:SECTION|SEC-)(\d+[A-Z]\.\d{2})", query_upper))
        exact_codes.update(f"TABLE-{chapter}-{int(number)}" for chapter, number in
                           re.findall(r"TABLE-?(\d+[A-Z])-?(\d+)", query_upper))
        reranked = sorted(
            ((score + (75.0 if self.units[index]["source_unit_code"] in exact_codes else 0.0), index)
             for score, index in ranked), key=lambda value: (-value[0], value[1])
        )
        selected = reranked[offset:offset + page_size]
        items = []
        for rank_offset, (score, index) in enumerate(selected, offset + 1):
            row = self.units[index]
            items.append({
                "rank": rank_offset, "score": round(float(score), 6),
                "source_unit_code": row["source_unit_code"], "unit_type": row["unit_type"],
                "title": row["title"], "chapter": row["chapter"],
                "figure_code": row.get("figure_code"), "source_pages": row["source_pages"],
                "printed_pages": row["printed_pages"], "available_regions": row["available_regions"],
                "source_excerpt": row["raw_text"][:1200],
            })
        next_offset = offset + len(selected)
        result = {
            "operation": "search_manual", "query": query,
            "corpus_scope": "entire frozen MUTCD 11th Edition structured index",
            "candidate_source_unit_count": len(self.units), "items": items,
            "continuation_token": _token("search", key, next_offset) if next_offset < len(reranked) else None,
            "has_more": next_offset < len(reranked),
            "recognized_manual_source_unit_codes": sorted(exact_codes),
            "correct_page_or_application_whitelist": None,
        }
        return self._record("search_manual", query, result)

    def search_manual_by_structure(self, query: str, source_code_prefixes: list[str],
                                   result_limit: int = 30) -> dict:
        """Rank a broad concept inside a declared MUTCD structural partition.

        This keeps recall from depending on clause-like query wording. The
        partition is a domain-level manual route (for example Part 6H), never a
        whitelist of expected sections, paragraphs, or citations.
        """
        if not query.strip():
            raise ValueError("query must be non-empty natural language")
        prefixes = tuple(dict.fromkeys(prefix.strip().upper()
                                       for prefix in source_code_prefixes if prefix.strip()))
        if not prefixes:
            raise ValueError("at least one source-code prefix is required")
        pool = [row for row in self.units
                if str(row.get("source_unit_code", "")).upper().startswith(prefixes)]
        ranked = bm25_rank(query, [self._unit_document(row) for row in pool])
        selected = ranked[:max(1, int(result_limit))]
        items = []
        for rank, (score, index) in enumerate(selected, 1):
            row = pool[index]
            items.append({
                "rank": rank, "score": round(float(score), 6),
                "source_unit_code": row["source_unit_code"], "unit_type": row["unit_type"],
                "title": row["title"], "chapter": row["chapter"],
                "figure_code": row.get("figure_code"), "source_pages": row["source_pages"],
                "printed_pages": row["printed_pages"], "available_regions": row["available_regions"],
                "source_excerpt": row["raw_text"][:1200],
            })
        return self._record("search_manual_by_structure", query, {
            "operation": "search_manual_by_structure", "query": query,
            "corpus_scope": "declared MUTCD structural partition",
            "source_code_prefixes": list(prefixes),
            "candidate_source_unit_count": len(pool), "items": items,
            "continuation_token": None, "has_more": len(ranked) > len(selected),
            "correct_page_or_application_whitelist": None,
        })

    def expand_source_unit(self, source_unit_code: str, region: str | None = None,
                           page_size: int = 20, continuation_token: str | None = None) -> dict:
        code = _normalized_source_code(source_unit_code)
        if code not in self.unit_by_code:
            raise ValueError("unknown MUTCD-native source unit code")
        page_size = min(max(int(page_size), 1), self.max_items_per_response)
        region_key = region or "*"
        key = f"{code}|{region_key}"
        offset = _decode(continuation_token, "expand", key)
        nodes = self.nodes_by_unit.get(code, [])
        if region:
            nodes = [row for row in nodes if row["region"] == region]
        nodes = sorted(nodes, key=lambda row: (row["source"]["pdf_page"], row.get("paragraph", ""), row["node_id"]))
        selected = nodes[offset:offset + page_size]
        unit = self.unit_by_code[code]
        next_offset = offset + len(selected)
        item_views = [self._node_view(row) for row in selected]
        result = {
            "operation": "expand_source_unit", "source_unit_code": code, "region": region,
            "source_unit_metadata": {
                "unit_type": unit["unit_type"], "title": unit["title"], "chapter": unit["chapter"],
                "figure_code": unit.get("figure_code"), "source_pages": unit["source_pages"],
                "printed_pages": unit["printed_pages"],
            },
            "items": item_views, "matching_node_count": len(nodes),
            "continuation_token": _token("expand", key, next_offset) if next_offset < len(nodes) else None,
            "has_more": next_offset < len(nodes),
        }
        figure_images = sorted({row["figure_image_path"] for row in item_views
                                if row.get("figure_image_path")})
        if figure_images:
            result["_image_paths"] = figure_images
        return self._record("expand_source_unit", key, result)

    def follow_cross_reference(self, from_source_unit_code: str,
                               to_source_unit_code: str | None = None) -> dict:
        source = _normalized_source_code(from_source_unit_code)
        target_filter = _normalized_source_code(to_source_unit_code) if to_source_unit_code else None
        edges = self.edges_by_source.get(source, [])
        if target_filter:
            edges = [row for row in edges if row["to_source_unit_code"] == target_filter]
        items = []
        for edge in edges:
            target = self.unit_by_code.get(edge["to_source_unit_code"])
            items.append({
                "edge_id": edge["edge_id"], "from_source_unit_code": edge["from_source_unit_code"],
                "to_source_unit_code": edge["to_source_unit_code"], "relation": edge["relation"],
                "source_span": edge["source"]["source_span"],
                "target_source_unit_metadata": None if not target else {
                    "unit_type": target["unit_type"], "title": target["title"],
                    "chapter": target["chapter"], "source_pages": target["source_pages"],
                    "printed_pages": target["printed_pages"],
                },
            })
        return self._record("follow_cross_reference", source, {
            "operation": "follow_cross_reference", "manual_edge_required": True,
            "from_source_unit_code": source, "items": items,
        })

    def read_source_node(self, source_node_id: str) -> dict:
        matches = [row for row in self.nodes if row["node_id"] == source_node_id]
        if not matches:
            raise ValueError("unknown source hash node")
        return self._record("read_source_node", source_node_id, {
            "operation": "read_source_node", "items": [self._node_view(matches[0])],
        })

    def resource_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.resources))
