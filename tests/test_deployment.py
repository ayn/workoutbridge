import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_multiuser_factory_requires_a_vault_key_instead_of_silently_saving_plaintext(self):
        from workoutbridge.web import application

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "WORKOUTBRIDGE_MULTIUSER": "true",
                    "WORKOUTBRIDGE_DATA_DIR": directory,
                    "WORKOUTBRIDGE_ORIGIN": "https://bridge.example",
                    "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
                    "CLOUDFLARE_EMAIL_TOKEN_FILE": "/private/unused",
                },
                clear=True,
            ),
        ):
            with self.assertRaises(KeyError):
                app = application()
                self.addCleanup(app.state.scheduler.close)

    def test_multiuser_deployment_keeps_credentials_in_read_only_secrets_and_requires_vault(self):
        compose = (ROOT / "deploy/compose.multiuser.yaml").read_text()
        self.assertIn("WORKOUTBRIDGE_MULTIUSER", compose)
        self.assertIn("WORKOUTBRIDGE_HOSTED_PLANS", compose)
        self.assertIn("/run/secrets/provider_key", compose)
        self.assertIn("/run/secrets/cloudflare_email", compose)
        apache = (ROOT / "deploy/apache-prescribed.conf").read_text()
        self.assertIn("ServerName prescribed.fit", apache)
        self.assertIn("ProxyPreserveHost On", apache)
        self.assertIn("http://127.0.0.1:1879/", apache)
        self.assertNotIn("LogFormat combined", apache)

    def test_coros_dependencies_available_in_ci_and_container(self):
        for path in ("Dockerfile", ".github/workflows/tests.yml"):
            self.assertIn("--extra coros", (ROOT / path).read_text())

    def test_stripe_override_requires_private_secret_files_and_defaults_to_test(self):
        compose = (ROOT / "deploy/compose.stripe.yaml").read_text()
        for value in (
            "STRIPE_ENABLED",
            "STRIPE_LIVE_MODE:-false",
            "/run/secrets/stripe_key",
            "/run/secrets/stripe_webhook",
            "STRIPE_MONTHLY_PRICE_ID",
            "STRIPE_YEARLY_PRICE_ID",
        ):
            self.assertIn(value, compose)
        self.assertNotIn("sk_live_", compose)

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
