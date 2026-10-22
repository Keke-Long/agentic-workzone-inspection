#!/usr/bin/env python3
"""Minimal Responses API helpers shared by the current experiment."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def image_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def credentials(cfg: dict) -> tuple[str, str]:
    key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if key:
        return key, (base_url or "https://api.openai.com").rstrip("/")
    credential_config = cfg.get("credential_config")
    if not credential_config:
        raise RuntimeError(
            "No project-authorized OpenAI credential is configured. Set OPENAI_API_KEY "
            "or configure a credential file inside experiments/agentic_inspection."
        )
    project_root = Path(__file__).resolve().parents[1]
    approved_user_credential = Path.home() / ".config/workzone/openai_credentials.json"
    credential_path = Path(credential_config).expanduser().resolve()
    if not credential_path.is_relative_to(project_root) and credential_path != approved_user_credential:
        raise RuntimeError("credential_config is not an approved project-owned credential path")
    legacy = load_json(credential_path)
    return legacy["api_key"], legacy.get("base_url", "https://api.openai.com").rstrip("/")


def post_json(url: str, key: str, payload: dict, timeout: int = 300) -> tuple[dict, float]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Responses API HTTP {exc.code}: {body[:2000]}") from exc
    return result, time.monotonic() - start


def output_text(response: dict) -> str:
    chunks = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    if not chunks:
        raise RuntimeError("No output_text in response")
    return "".join(chunks)
