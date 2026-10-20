import io
import json
import logging
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from workoutbridge.cli import main


@unittest.skipIf(sys.version_info < (3, 12), "Garmin extra requires Python 3.12+")
class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Path(self.tmp.name) / "session"

    def call(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["auth", "garmin", "--session-dir", str(self.session)])
        return code, out.getvalue(), err.getvalue()

    @patch("workoutbridge.auth.getpass", side_effect=["synthetic-password", "123456"])
    @patch("workoutbridge.auth.input", return_value="test@example.invalid")
    @patch("workoutbridge.auth.make_client")
    def test_interactive_login_private_session_and_mfa(self, factory, email, secret):
        client = Mock(profile_id=12345)
        factory.return_value = client

        def login(*, tokenstore):
            self.assertEqual(Path(tokenstore), self.session)
            self.assertEqual(self.session.stat().st_mode & 0o777, 0o700)
            self.assertEqual(factory.call_args.kwargs["prompt_mfa"](), "123456")
            (self.session / "garmin_tokens.json").write_text('{"synthetic": true}')

        client.login.side_effect = login
        before = os.umask(0o022)
        try:
            code, out, err = self.call()
            after = os.umask(0o022)
        finally:
            os.umask(before)
        self.assertEqual(after, 0o022)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["account_id"], "12345")
        self.assertEqual(err, "")
        self.assertNotIn("synthetic-password", out)
        self.assertEqual((self.session / "garmin_tokens.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(factory.call_args.args, ("test@example.invalid", "synthetic-password"))
        self.assertEqual([c[0] for c in client.method_calls], ["login"])

    @patch("workoutbridge.auth.getpass", return_value="secret")
    @patch("workoutbridge.auth.input", return_value="test@example.invalid")
    @patch("workoutbridge.auth.make_client")
    def test_failure_redacted_and_logging_restored(self, factory, email, secret):
        def fail(*args, **kwargs):
            logging.error("synthetic-secret")
            raise RuntimeError("synthetic-secret")

        factory.return_value.login.side_effect = fail
        before = logging.root.manager.disable
        code, out, err = self.call()
        self.assertEqual(code, 2)
        self.assertNotIn("synthetic-secret", out + err)
        self.assertEqual(logging.root.manager.disable, before)

    @patch("workoutbridge.auth.make_client")
    @patch("workoutbridge.auth.input")
    def test_existing_directory_never_overwritten(self, email, factory):
        self.session.mkdir()
        token = self.session / "garmin_tokens.json"
        token.write_text("existing")
        self.assertEqual(self.call()[0], 2)
        self.assertEqual(token.read_text(), "existing")
        email.assert_not_called()
        factory.assert_not_called()

    @patch("workoutbridge.auth.make_client")
    @patch("workoutbridge.auth.input")
    def test_symlink_directory_rejected(self, email, factory):
        self.session.symlink_to(self.tmp.name, target_is_directory=True)
        self.assertEqual(self.call()[0], 2)
        email.assert_not_called()

    @patch("workoutbridge.auth.getpass", return_value="secret")
    @patch("workoutbridge.auth.input", return_value="test@example.invalid")
    @patch("workoutbridge.auth.make_client")
    def test_missing_profile_or_tokens_not_success(self, factory, email, secret):
        factory.return_value.profile_id = None
        self.assertEqual(self.call()[0], 2)

    @patch("workoutbridge.auth.getpass", return_value="secret")
    @patch("workoutbridge.auth.input", return_value="test@example.invalid")
    @patch("workoutbridge.auth.make_client")
    def test_profile_without_saved_tokens_not_success(self, factory, email, secret):
        factory.return_value.profile_id = 12345
        self.assertEqual(self.call()[0], 2)

    @patch("workoutbridge.auth.getpass", side_effect=KeyboardInterrupt)
    @patch("workoutbridge.auth.input", return_value="test@example.invalid")
    def test_cancel_is_clean(self, email, secret):
        code, out, err = self.call()
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
