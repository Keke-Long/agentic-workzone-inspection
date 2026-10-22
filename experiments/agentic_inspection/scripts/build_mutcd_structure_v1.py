#!/usr/bin/env python3
"""Build the frozen MUTCD structure before any test-scene query is evaluated."""

from __future__ import annotations

import json
from pathlib import Path

from mutcd_structure_v1 import write_index
from project_common import ROOT, load_config


def main() -> None:
    cfg = load_config()
    index_path = ROOT / cfg["retrieval"]["manual_structure_index"]
    manifest = write_index(Path(cfg["source"]["manual_pdf"]), index_path)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
