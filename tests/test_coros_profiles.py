import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workoutbridge.profiles import authenticate_profile, load_profile


class CorosProfileTests(unittest.TestCase):
    def test_coros_profile_and_reauthentication_preserve_account_and_ledger(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"WORKOUTBRIDGE_CONFIG_DIR": directory}),
        ):
            profile = authenticate_profile(
                "coros-test",
                Path(directory) / "session",
                destination="coros",
                authenticator=lambda _: "coros:us:synthetic",
            )
            self.assertEqual(load_profile("coros-test")["destination"], "coros")
            again = authenticate_profile(
                "coros-test",
                Path(directory) / "new-session",
                destination="coros",
                authenticator=lambda _: "coros:us:synthetic",
            )
            self.assertEqual(profile["state_db"], again["state_db"])
            with self.assertRaises(ValueError):
                authenticate_profile(
                    "coros-test", destination="coros", authenticator=lambda _: "coros:us:other"
                )
            with self.assertRaises(ValueError):
                authenticate_profile("coros-test", authenticator=lambda _: "123")
