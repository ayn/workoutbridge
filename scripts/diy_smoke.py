"""Isolated DIY application lifecycle smoke; no provider or hosted-service access."""

import builtins
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def run():
    original_import = builtins.__import__

    def diy_import(name, *args, **kwargs):
        if name.split(".")[0] in {"stripe", "webauthn", "prescribed"}:
            raise ImportError("DIY must not import hosted-only dependencies")
        return original_import(name, *args, **kwargs)

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        password = root / "access-password"
        password.write_text("synthetic-diy-password-" + "x" * 32)
        password.chmod(0o600)
        with (
            patch.dict(
                os.environ,
                {
                    "WORKOUTBRIDGE_DATA_DIR": str(root / "data"),
                    "WORKOUTBRIDGE_CONFIG_DIR": str(root / "config"),
                    "WORKOUTBRIDGE_PASSWORD_FILE": str(password),
                    "WORKOUTBRIDGE_ORIGIN": "https://diy.example",
                },
                clear=True,
            ),
            patch("builtins.__import__", side_effect=diy_import),
        ):
            from fastapi.testclient import TestClient

            from workoutbridge.web import application

            with TestClient(application(), base_url="https://diy.example") as client:
                assert client.get("/api/v1/state").status_code == 401
                response = client.post(
                    "/api/v1/login",
                    json={"password": password.read_text()},
                    headers={"Origin": "https://diy.example"},
                )
                assert response.status_code == 200
                state = client.get("/api/v1/state")
                assert state.status_code == 200
                assert state.json()["sources"] == []
                assert state.json()["connections"] == []
                response = client.post(
                    "/api/v1/logout", json={}, headers={"Origin": "https://diy.example"}
                )
                assert response.status_code == 200
                assert client.get("/api/v1/state").status_code == 401
    print("DIY smoke passed: isolated startup, login, API, logout and shutdown")


if __name__ == "__main__":
    run()
