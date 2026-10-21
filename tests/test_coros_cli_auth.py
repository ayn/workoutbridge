import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from workoutbridge.cli import main
from workoutbridge.profiles import load_profile


class CorosCliAuthTests(unittest.TestCase):
    def test_cli_browser_login_and_finish_save_profile(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"WORKOUTBRIDGE_CONFIG_DIR": directory}),
        ):
            args = [
                "auth",
                "coros",
                "--profile",
                "coros-test",
                "--session-dir",
                str(Path(directory) / "session"),
            ]
            with (
                patch(
                    "workoutbridge.coros_auth.begin_login",
                    return_value={
                        "login_url": "https://mcpus.coros.com/cli/login/synthetic",
                        "expires_in": 600,
                    },
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main(args), 0)
                self.assertIn("login_url", json.loads(output.getvalue()))
            with (
                patch("workoutbridge.coros_auth.finish_login", return_value=None),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main(args + ["--finish"]), 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "pending")
            with (
                patch("workoutbridge.coros_auth.finish_login", return_value="coros:us:synthetic"),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(args + ["--finish"]), 0)
            self.assertEqual(load_profile("coros-test")["destination"], "coros")
