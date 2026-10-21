import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workoutbridge.profiles import load_profile
from workoutbridge.web_auth import GarminLogin


@unittest.skipIf(sys.version_info < (3, 12), "Garmin extra requires Python 3.12+")
class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"WORKOUTBRIDGE_CONFIG_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.login = GarminLogin(threading.RLock(), timeout=1)
        self.addCleanup(self.login.close)

    def wait(self, status):
        for _ in range(200):
            result = self.login.status()
            if result["status"] == status:
                return result
            time.sleep(0.01)
        self.fail(f"Expected {status}; got {result}")

    def factory(self, email, password, *, prompt_mfa):
        self.assertEqual((email, password), ("example@example.invalid", "PRIVATE"))
        client = Mock(profile_id=123)

        def login(*, tokenstore):
            self.assertEqual(prompt_mfa(), "123456")
            Path(tokenstore, "garmin_tokens.json").write_text('{"token":"synthetic"}')

        client.login.side_effect = login
        return client

    def test_mfa_private_persistence_and_no_credentials_in_status(self):
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            job = self.login.start("personal", "example@example.invalid", "PRIVATE")
            status = self.wait("mfa")
            self.assertNotIn("PRIVATE", json.dumps(status))
            self.login.submit(job["id"], "123456")
            self.wait("complete")
        p = load_profile("personal")
        self.assertEqual(p["account_id"], "123")
        self.assertEqual(Path(p["session_dir"], "garmin_tokens.json").stat().st_mode & 0o777, 0o600)
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn("PRIVATE", path.read_text())

    def test_cancel_and_timeout_never_save_profile(self):
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            job = self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("mfa")
            self.login.cancel(job["id"])
            self.login.close()
        self.assertFalse((self.root / "profiles/personal.json").exists())
        self.login = GarminLogin(threading.RLock(), timeout=0.03)
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("failed")
        self.assertFalse((self.root / "profiles/personal.json").exists())

    def test_mfa_rejects_wrong_job_and_parallel_login(self):
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            job = self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("mfa")
            with self.assertRaises(ValueError):
                self.login.start("other", "example@example.invalid", "PRIVATE")
            with self.assertRaises(ValueError):
                self.login.submit("wrong", "123456")
            self.login.cancel(job["id"])
            self.login.close()

    def test_failed_reauth_preserves_existing_profile_and_receipts(self):
        from workoutbridge.profiles import authenticate_profile

        with patch("workoutbridge.auth.authenticate", return_value="999"):
            old = authenticate_profile("personal")
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            job = self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("mfa")
            self.login.submit(job["id"], "123456")
            status = self.wait("failed")
        self.assertEqual(load_profile("personal"), old)
        self.assertNotIn("PRIVATE", json.dumps(status))

    def test_rate_limit_and_input_validation(self):
        with self.assertRaises(ValueError):
            self.login.start("../bad", "example@example.invalid", "PRIVATE")
        with patch("workoutbridge.auth.make_client", side_effect=RuntimeError("PRIVATE")):
            for _ in range(3):
                self.login.start("personal", "example@example.invalid", "PRIVATE")
                self.wait("failed")
                self.login.close()
            with self.assertRaises(ValueError):
                self.login.start("personal", "example@example.invalid", "PRIVATE")

    def test_no_mfa_and_same_account_renewal_preserve_database(self):
        def factory(*args, **kwargs):
            client = Mock(profile_id=123)
            client.login.side_effect = lambda *, tokenstore: Path(
                tokenstore, "garmin_tokens.json"
            ).write_text('{"token":"synthetic"}')
            return client

        with patch("workoutbridge.auth.make_client", side_effect=factory):
            self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("complete")
            self.login.close()
            first = load_profile("personal")
            self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("complete")
            self.login.close()
            second = load_profile("personal")
        self.assertEqual(first["state_db"], second["state_db"])
        self.assertNotEqual(first["session_dir"], second["session_dir"])

    def test_hosted_auth_keeps_session_plaintext_only_in_runtime_and_seals_before_success(self):
        from cryptography.fernet import Fernet

        from workoutbridge.vault import SessionVault

        vault = SessionVault(self.root / "sealed", self.root / "runtime", Fernet.generate_key())
        self.login = GarminLogin(threading.RLock(), config_root=self.root / "config", vault=vault)
        with patch("workoutbridge.auth.make_client", side_effect=self.factory):
            job = self.login.start("personal", "example@example.invalid", "PRIVATE")
            self.wait("mfa")
            self.login.submit(job["id"], "123456")
            self.wait("complete")
        profile = load_profile("personal", config_root=self.root / "config")
        self.assertEqual(Path(profile["session_dir"]).parent, self.root / "runtime")
        sealed = list((self.root / "sealed").glob("*.sealed"))
        self.assertEqual(len(sealed), 1)
        self.assertNotIn(b"synthetic", sealed[0].read_bytes())
        self.assertFalse((self.root / "config/sessions").exists())
