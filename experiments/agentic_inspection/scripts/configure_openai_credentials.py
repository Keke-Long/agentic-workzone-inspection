#!/usr/bin/env python3
"""Interactively install a project-owned OpenAI API key without echoing it."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request


CREDENTIAL_PATH = Path.home() / ".config/workzone/openai_credentials.json"
DEFAULT_BASE_URL = "https://api.openai.com"
TARGET_MODEL = "gpt-5.6-luna"


def verify_key(api_key: str, base_url: str) -> tuple[int, bool]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI credential verification failed with HTTP {exc.code}: {body[:500]}") from exc
    model_ids = {row.get("id") for row in payload.get("data", [])}
    return len(model_ids), TARGET_MODEL in model_ids


def main() -> None:
    print("Configure the project-owned OpenAI credential.")
    print("The API key is entered with hidden input and is never printed.")
    api_key = getpass.getpass("OpenAI project API key: ").strip()
    if not api_key:
        raise SystemExit("No API key supplied; nothing was written.")
    base_url = input(f"Base URL [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    organization_label = input("Organization label for local audit (optional): ").strip()
    project_label = input("Project label for local audit (optional): ").strip()
    model_count, target_available = verify_key(api_key, base_url)
    CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CREDENTIAL_PATH.parent, 0o700)
    payload = {
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "organization_label": organization_label or None,
        "project_label": project_label or None,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".openai_credentials.", suffix=".tmp", dir=CREDENTIAL_PATH.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, CREDENTIAL_PATH)
        os.chmod(CREDENTIAL_PATH, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"Credential saved with mode 0600: {CREDENTIAL_PATH}")
    print(f"Visible models: {model_count}; {TARGET_MODEL} available: {target_available}")
    print("No paid model request was made. Model execution remains locked.")


if __name__ == "__main__":
    main()
