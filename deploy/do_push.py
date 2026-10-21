#!/usr/bin/env python3
"""Send a tested image to the private DO target without persisting registry credentials."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def push(config_path, *, run=subprocess.run):
    revision = os.environ["REVISION"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Expected tested commit SHA")
    current = run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.split()
    if not current or current[0] != revision:
        print("Superseded revision; skipping DO deployment")
        return
    config_path = Path(config_path)
    if config_path.is_symlink() or config_path.stat().st_mode & 0o077:
        raise ValueError("DO target configuration must be private")
    config = json.loads(config_path.read_text())
    if not re.fullmatch(r"[A-Za-z0-9.-]+", config["host"]) or not re.fullmatch(
        r"[a-z_][a-z0-9_-]*", config["user"]
    ):
        raise ValueError("Invalid DO target")
    payload = {
        "revision": revision,
        "digest": os.environ["IMAGE_DIGEST"],
        "registry_user": os.environ["REGISTRY_USER"],
        "registry_token": os.environ["REGISTRY_TOKEN"],
    }
    run(
        [
            "ssh",
            "-T",
            "-F",
            "/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + config["known_hosts"],
            "-i",
            config["key"],
            config["user"] + "@" + config["host"],
        ],
        input=json.dumps(payload),
        text=True,
        check=True,
        timeout=480,
    )


if __name__ == "__main__":
    try:
        push(Path.home() / ".config/workoutbridge-do-target.json")
    except Exception:  # noqa: BLE001 - do not print registry credentials or SSH payloads.
        print(
            "DO deployment failed; inspect the target service and preserved receipt.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
