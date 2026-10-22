#!/usr/bin/env python3
"""Deterministic dense ranking over frozen MUTCD normative provisions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from project_common import sha256


class DenseGapIndex:
    def __init__(self, index_path: Path, manifest_path: Path,
                 structure_path: Path, graph_path: Path) -> None:
        self.index_path = index_path
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != "mutcd_dense_gap_index_v1":
            raise ValueError("unsupported dense gap index schema")
        if self.manifest.get("index_sha256") != sha256(index_path):
            raise ValueError("dense gap index hash does not match its manifest")
        if self.manifest.get("source_structure_sha256") != sha256(structure_path):
            raise ValueError("dense gap index was not built from the active structure index")
        if self.manifest.get("knowledge_graph_sha256") != sha256(graph_path):
            raise ValueError("dense gap index was not built from the active knowledge graph")

        data = np.load(index_path, allow_pickle=False)
        self.provision_ids = [str(value) for value in data["provision_ids"]]
        self.passage_embeddings = np.asarray(data["passage_embeddings"], dtype=np.float32)
        domains = [str(value) for value in data["query_domains"]]
        query_embeddings = np.asarray(data["query_embeddings"], dtype=np.float32)
        self.query_embedding_by_domain = dict(zip(domains, query_embeddings))
        if len(self.provision_ids) != len(self.passage_embeddings):
            raise ValueError("dense provision IDs and embeddings have different lengths")
        self.index_by_provision_id = {
            provision_id: index for index, provision_id in enumerate(self.provision_ids)
        }

    def rank(self, domain: str, provision_ids: list[str]) -> list[tuple[float, str]]:
        if domain not in self.query_embedding_by_domain:
            raise ValueError(f"dense index has no query embedding for domain: {domain}")
        unknown = sorted(set(provision_ids) - set(self.index_by_provision_id))
        if unknown:
            raise ValueError(f"dense index lacks normative provisions: {unknown[:5]}")
        query = self.query_embedding_by_domain[domain]
        ranked = [
            (float(self.passage_embeddings[self.index_by_provision_id[item]] @ query), item)
            for item in provision_ids
        ]
        return sorted(ranked, key=lambda row: (-row[0], row[1]))

