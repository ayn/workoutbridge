#!/usr/bin/env python3
"""Restricted deployment entry point; receives an image digest and temporary pull token."""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE = "ghcr.io/ayn/workoutbridge"
SOURCE = "https://github.com/ayn/workoutbridge"


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".deploy-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def deploy(root, payload, *, run=subprocess.run):
    if (
        not isinstance(payload, dict)
        or set(payload) != {"revision", "digest", "registry_user", "registry_token"}
        or not re.fullmatch(r"[a-f0-9]{40}", str(payload.get("revision", "")))
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(payload.get("digest", "")))
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", str(payload.get("registry_user", ""))
        )
        or not isinstance(payload.get("registry_token"), str)
        or not 1 <= len(payload["registry_token"]) <= 4096
    ):
        raise ValueError("Invalid deployment request")
    root = Path(root)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError("Deployment directory must be private")
    lock_fd = os.open(root / "deploy.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads((root / "deploy.json").read_text())
        image = IMAGE + "@" + payload["digest"]
        environment = {**os.environ, "DOCKER_HOST": config["socket"], "WORKOUTBRIDGE_IMAGE": image}
        docker = config["docker"]

        def checked(arguments, **kwargs):
            result = run(
                arguments, text=True, capture_output=True, env=environment, timeout=180, **kwargs
            )
            if result.returncode:
                raise ValueError(
                    "Deployment command failed; inspect service health before retrying"
                )
            return result.stdout

        with tempfile.TemporaryDirectory(prefix="registry-", dir=root) as authentication:
            checked(
                [
                    docker,
                    "--config",
                    authentication,
                    "login",
                    "ghcr.io",
                    "--username",
                    payload["registry_user"],
                    "--password-stdin",
                ],
                input=payload["registry_token"],
            )
            checked([docker, "--config", authentication, "pull", image])
            labels = json.loads(
                checked([docker, "image", "inspect", "--format", "{{json .Config.Labels}}", image])
            )
            if (
                labels.get("org.opencontainers.image.revision") != payload["revision"]
                or labels.get("org.opencontainers.image.source") != SOURCE
            ):
                raise ValueError("Image revision or source does not match the deployment request")
            checked(
                [
                    docker,
                    "compose",
                    "--project-name",
                    "workoutbridge",
                    "--env-file",
                    config["env_file"],
                    "-f",
                    config["compose"],
                    *[
                        argument
                        for path in config.get("overrides", [])
                        for argument in ("-f", path)
                    ],
                    "up",
                    "-d",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "90",
                ]
            )
        previous = root / "current.json"
        if previous.exists():
            atomic_json(root / "previous.json", json.loads(previous.read_text()))
        record = {"revision": payload["revision"], "digest": payload["digest"], "image": image}
        atomic_json(previous, record)
        return record


def main():
    os.umask(0o077)
    try:
        if os.environ.get("SSH_ORIGINAL_COMMAND"):
            raise ValueError("Remote commands are not accepted")
        data = sys.stdin.buffer.read(16385)
        if len(data) > 16384:
            raise ValueError("Deployment request exceeds size limit")
        record = deploy(Path.home() / ".config/workoutbridge-deploy", json.loads(data))
    except Exception:  # noqa: BLE001 - never echo registry credentials or remote output.
        print(
            "Deployment failed. Current receipt preserved; inspect service health.", file=sys.stderr
        )
        return 1
    print(json.dumps({"status": "healthy", **record}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
