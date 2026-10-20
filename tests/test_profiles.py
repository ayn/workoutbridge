import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_calendar import calendar
from test_publishing import FakeGarmin

from workoutbridge.cli import main
from workoutbridge.profiles import load_profile


class ProfileTests(unittest.TestCase):
    def test_existing_database_can_be_selected_once_and_not_changed_on_reauth(self):
        database = Path(self.tmp.name) / "existing.sqlite"
        with patch("workoutbridge.auth.authenticate", return_value="12345"):
            self.assertEqual(
                self.call(
                    [
                        "auth",
                        "garmin",
                        "--profile",
                        "personal",
                        "--state-db",
                        str(database),
                    ]
                )[0],
                0,
            )
        self.assertEqual(load_profile("personal")["state_db"], str(database))
        with patch("workoutbridge.auth.authenticate") as auth:
            self.assertEqual(
                self.call(
                    [
                        "auth",
                        "garmin",
                        "--profile",
                        "personal",
                        "--state-db",
                        str(Path(self.tmp.name) / "different.sqlite"),
                    ]
                )[0],
                2,
            )
            auth.assert_not_called()
        self.auth()
        self.assertEqual(load_profile("personal")["state_db"], str(database))

    def test_wrong_profile_plan_rejected_before_connect(self):
        provider = FakeGarmin()
        provider.account_id = "12345"
        self.auth()
        from workoutbridge.calendar import Event
        from workoutbridge.cli import review_item
        from workoutbridge.publishing import digest

        event = Event("synthetic", "example", "", "2027-01-05", "Run 20 min", "")
        bundle = {"version": 1, "account_id": "67890", "items": [review_item("67890", event)]}
        bundle["review_hash"] = digest(bundle)
        path = Path(self.tmp.name) / "wrong.json"
        path.write_text(json.dumps(bundle))
        with patch("workoutbridge.cli.GarminProvider.connect") as connect:
            self.assertEqual(
                self.call(["publish", str(path), "--profile", "personal", "--yolo"])[0], 2
            )
            connect.assert_not_called()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "private"
        env = patch.dict(os.environ, {"WORKOUTBRIDGE_CONFIG_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = main(args)
        return result, out.getvalue(), err.getvalue()

    def auth(self, name="personal", account="12345"):
        with patch("workoutbridge.auth.authenticate", return_value=account) as authenticate:
            code, out, _ = self.call(["auth", "garmin", "--profile", name])
        self.assertEqual(code, 0)
        return authenticate.call_args.args[0], json.loads(out)

    def test_auth_persists_identity_paths_and_private_permissions(self):
        session, result = self.auth()
        profile = load_profile("personal")
        self.assertEqual(profile["account_id"], "12345")
        self.assertEqual(profile["destination"], "garmin")
        self.assertEqual(Path(profile["session_dir"]), session)
        self.assertEqual(result["profile"], "personal")
        path = self.root / "profiles" / "personal.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn("password", path.read_text())

    def test_reauth_preserves_database_and_requires_same_account(self):
        old_session, _ = self.auth()
        before = load_profile("personal")
        new_session, _ = self.auth()
        self.assertNotEqual(old_session, new_session)
        self.assertEqual(before["state_db"], load_profile("personal")["state_db"])
        saved = load_profile("personal")
        with patch("workoutbridge.auth.authenticate", return_value="99999"):
            self.assertEqual(self.call(["auth", "garmin", "--profile", "personal"])[0], 2)
        self.assertEqual(saved, load_profile("personal"))

    def test_failure_does_not_save_profile(self):
        with patch("workoutbridge.auth.authenticate", side_effect=RuntimeError("secret")):
            code, out, err = self.call(["auth", "garmin", "--profile", "personal"])
        self.assertEqual(code, 2)
        self.assertNotIn("secret", out + err)
        self.assertFalse((self.root / "profiles" / "personal.json").exists())

    def test_names_and_missing_profiles_fail_without_authentication(self):
        for name in ("../escape", "/absolute", "a/b", "", "missing"):
            with self.subTest(name=name), patch("workoutbridge.cli.GarminProvider.connect") as conn:
                self.assertEqual(
                    self.call(["garmin-check", "--profile", name, "--date", "2027-01-05"])[0], 2
                )
                conn.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_profiles_isolate_accounts_and_reject_overrides(self):
        self.auth()
        self.auth("second", "67890")
        self.assertNotEqual(
            load_profile("personal")["state_db"], load_profile("second")["state_db"]
        )
        with patch("workoutbridge.cli.GarminProvider.connect") as conn:
            self.assertEqual(
                self.call(
                    [
                        "garmin-check",
                        "--profile",
                        "personal",
                        "--account-id",
                        "67890",
                        "--date",
                        "2027-01-05",
                    ]
                )[0],
                2,
            )
            conn.assert_not_called()

    def test_read_check_uses_persisted_expected_account(self):
        self.auth()
        provider = FakeGarmin()
        provider.account_id = "12345"
        with patch("workoutbridge.cli.GarminProvider.connect", return_value=provider) as conn:
            self.assertEqual(
                self.call(
                    [
                        "garmin-check",
                        "--profile",
                        "personal",
                        "--date",
                        "2027-01-05",
                    ]
                )[0],
                0,
            )
            self.assertEqual(conn.call_args.kwargs["expected_account"], "12345")

    def test_plan_dry_run_and_publish_use_profile_without_duplicate_writes(self):
        provider = FakeGarmin()
        provider.account_id = "12345"
        self.auth(account=provider.account_id)
        path = Path(self.tmp.name) / "synthetic.ics"
        path.write_bytes(
            calendar("UID:profile-test\r\nDTSTART;VALUE=DATE:20270105\r\nSUMMARY:Run 20 min")
        )
        code, out, _ = self.call(
            [
                "plan",
                str(path),
                "--profile",
                "personal",
                "--source",
                "synthetic",
                "--timezone",
                "UTC",
                "--start",
                "2027-01-01",
                "--end",
                "2027-02-01",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["account_id"], provider.account_id)
        self.assertNotIn(str(self.root), out)
        review = Path(self.tmp.name) / "review.json"
        review.write_text(out)
        args = ["publish", str(review), "--profile", "personal"]
        with patch("workoutbridge.cli.GarminProvider.connect") as conn:
            self.assertEqual(self.call(args)[0], 0)
            conn.assert_not_called()
        self.assertFalse(Path(load_profile("personal")["state_db"]).exists())
        with patch("workoutbridge.cli.GarminProvider.connect", return_value=provider):
            self.assertEqual(self.call(args + ["--yolo"])[0], 0)
            self.assertEqual(self.call(args + ["--yolo"])[0], 0)
        self.assertEqual((provider.uploads, provider.schedules), (1, 1))

    def test_symlink_and_corrupt_profile_rejected(self):
        self.auth()
        path = self.root / "profiles" / "personal.json"
        path.write_text('{"destination":"coros"}')
        with self.assertRaises(ValueError):
            load_profile("personal")
        path.unlink()
        path.symlink_to(Path(self.tmp.name) / "elsewhere")
        with self.assertRaises(ValueError):
            load_profile("personal")
