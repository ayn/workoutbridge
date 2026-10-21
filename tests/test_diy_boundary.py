import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiyBoundaryTests(unittest.TestCase):
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
