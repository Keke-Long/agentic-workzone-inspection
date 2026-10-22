#!/usr/bin/env python3
"""Current project paths, resource configuration, and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CONFIG_PATH = ROOT / "config/project_resources.json"


def load_config() -> dict:
    return json.loads(RESOURCE_CONFIG_PATH.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
