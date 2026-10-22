#!/usr/bin/env python3
"""Build the local E5 dense index used only by Stage 1C gap retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from mutcd_knowledge_graph_v2 import DOMAIN_GAP_QUERIES
from project_common import ROOT, sha256


MODEL_ID = "intfloat/e5-large-v2"
DEFAULT_OUTPUT = ROOT / "inputs/mutcd_dense_gap_e5_large_v2.npz"
DEFAULT_MANIFEST = ROOT / "inputs/mutcd_dense_gap_e5_large_v2_manifest.json"


def _passage(node: dict) -> str:
    source = node.get("source", {})
    return "passage: " + " ".join(str(node.get(key) or "") for key in (
        "source_unit_code", "chapter", "region", "subject", "relation", "threshold",
    )) + " " + str(source.get("source_span") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    structure_path = ROOT / "inputs/mutcd_structure_v1.json"
    graph_path = ROOT / "inputs/mutcd_knowledge_graph_v2.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    node_by_id = {row["node_id"]: row for row in structure["atomic_nodes"]}
    provision_ids = sorted(row["provision_id"] for row in graph["normative_provisions"])
    passages = [_passage(node_by_id[item]) for item in provision_ids]
    query_domains = list(DOMAIN_GAP_QUERIES)
    queries = ["query: " + DOMAIN_GAP_QUERIES[domain] for domain in query_domains]

    model = SentenceTransformer(MODEL_ID, local_files_only=True, device=args.device)
    passage_embeddings = model.encode(
        passages, batch_size=64, normalize_embeddings=True,
        show_progress_bar=True, convert_to_numpy=True,
    ).astype(np.float32)
    query_embeddings = model.encode(
        queries, batch_size=len(queries), normalize_embeddings=True,
        show_progress_bar=False, convert_to_numpy=True,
    ).astype(np.float32)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        provision_ids=np.asarray(provision_ids),
        passage_embeddings=passage_embeddings,
        query_domains=np.asarray(query_domains),
        query_embeddings=query_embeddings,
    )
    manifest = {
        "schema": "mutcd_dense_gap_index_v1",
        "model_id": MODEL_ID,
        "embedding_dimension": int(passage_embeddings.shape[1]),
        "normalized_embeddings": True,
        "passage_prefix": "passage: ",
        "query_prefix": "query: ",
        "provision_count": len(provision_ids),
        "query_domains": query_domains,
        "domain_queries": DOMAIN_GAP_QUERIES,
        "source_structure_sha256": sha256(structure_path),
        "knowledge_graph_sha256": sha256(graph_path),
        "index_path": str(args.output.resolve()),
        "index_sha256": sha256(args.output),
        "build_policy": {
            "scene_manifest_read": False,
            "hidden_reference_read": False,
            "outcome_labels_read": False,
            "passage_unit": "MUTCD normative atomic provision",
        },
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(args.output), "manifest": str(args.manifest),
        "provision_count": len(provision_ids),
        "embedding_dimension": int(passage_embeddings.shape[1]),
        "index_sha256": manifest["index_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
