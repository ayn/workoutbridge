import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_coros_dependencies_available_in_ci_and_container(self):
        for path in ("Dockerfile", ".github/workflows/tests.yml"):
            self.assertIn("--extra coros", (ROOT / path).read_text())

    def test_private_https_sidecar(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("network_mode: service:caddy", compose)
        self.assertIn('TS_ACCEPT_DNS: "false"', compose)
        self.assertIn('TS_BOOT_TIMEOUT: "30m"', compose)
        self.assertIn("WORKOUTBRIDGE_DOMAIN", compose)
        caddy = (ROOT / "Caddyfile").read_text()
        self.assertIn("reverse_proxy web:8000", caddy)
        self.assertIn("dns cloudflare", caddy)
        self.assertNotIn("443:443", compose)

    def test_private_container_contract(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("127.0.0.1:1879:8000", compose)
        self.assertIn("unless-stopped", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("max-size:", compose)
        self.assertIn("mem_limit:", compose)
        self.assertNotIn("docker.sock", compose)

    def test_deployment_only_after_trusted_main_ci(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        for text in (
            "workflow_run:",
            "branches: [main]",
            "== 'success'",
            "== 'push'",
            "workoutbridge-deploy",
            "head_sha",
            "contents: read",
        ):
            self.assertIn(text, workflow)
        self.assertNotIn("pull_request_target", workflow)

    def test_build_context_excludes_private_state(self):
        ignore = (ROOT / ".dockerignore").read_text()
        for path in (".env", ".git", "private", "*.sqlite*", "*.ics", "web/node_modules"):
            self.assertIn(path, ignore)
