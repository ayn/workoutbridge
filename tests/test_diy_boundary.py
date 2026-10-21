import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiyBoundaryTests(unittest.TestCase):
    def test_fresh_diy_smoke_without_hosted_configuration_or_imports(self):
        result = subprocess.run(
            [sys.executable, "scripts/diy_smoke.py"],
            cwd=ROOT,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DIY smoke passed", result.stdout)

    def test_ci_runs_minimal_diy_smoke_as_a_separate_job(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text()
        self.assertIn("diy-smoke:", workflow)
        self.assertIn("python scripts/diy_smoke.py", workflow)

    def test_managed_hosting_and_do_deployment_are_not_in_public_tree(self):
        for path in (
            "deploy",
            ".github/workflows/deploy-do.yml",
            "docs/digitalocean.md",
            "workoutbridge/hosted.py",
            "workoutbridge/billing.py",
            "web/src/Hosted.tsx",
        ):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists(), path)

    def test_self_hosted_web_has_no_billing_or_hosted_auth_dependencies(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        extras = " ".join(config["project"]["optional-dependencies"]["web"])
        self.assertNotIn("stripe", extras)
        self.assertNotIn("webauthn", extras)
        main = (ROOT / "web/src/main.tsx").read_text()
        self.assertIn("App", main)
        self.assertNotIn("Hosted", main)
