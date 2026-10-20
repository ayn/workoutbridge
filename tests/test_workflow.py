import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_calendar import calendar
from test_publishing import FakeGarmin

from workoutbridge.cli import main


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ics = self.root / "synthetic.ics"
        self.ics.write_bytes(
            calendar(
                "UID:synthetic-run\r\nDTSTART;VALUE=DATE:20270105"
                "\r\nSUMMARY:Track\r\nDESCRIPTION:Warm up until lap\\; "
                "4 x 200 m in 62-64 sec with 2 min walk/jog recovery",
            )
        )
        self.provider = FakeGarmin()

    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def plan(self):
        code, output, _ = self.call(
            [
                "plan",
                str(self.ics),
                "--source",
                "synthetic",
                "--timezone",
                "Asia/Taipei",
                "--start",
                "2027-01-01",
                "--end",
                "2027-02-01",
                "--account-id",
                self.provider.account_id,
            ]
        )
        self.assertEqual(code, 0)
        return json.loads(output)

    def publish_args(self, plan):
        path = self.root / "review.json"
        path.write_text(json.dumps(plan))
        return [
            "publish",
            str(path),
            "--account-id",
            self.provider.account_id,
            "--session-dir",
            str(self.root / "session"),
            "--state-db",
            str(self.root / "state.sqlite"),
        ]

    def test_ics_to_review_to_fake_garmin_twice(self):
        plan = self.plan()
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual(plan["items"][0]["event"]["title"], "Track")
        self.assertTrue(plan["items"][0]["draft"]["requires_review"])
        args = self.publish_args(plan) + ["--apply", "--approve", plan["review_hash"]]
        with patch("workoutbridge.cli.GarminProvider.connect", return_value=self.provider):
            self.assertEqual(self.call(args)[0], 0)
            self.assertEqual(self.call(args)[0], 0)
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))

    def test_dry_run_does_not_authenticate(self):
        plan = self.plan()
        with patch("workoutbridge.cli.GarminProvider.connect") as connect:
            code, output, _ = self.call(self.publish_args(plan))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["mode"], "dry-run")
        connect.assert_not_called()

    def test_apply_without_approval_does_not_authenticate(self):
        plan = self.plan()
        with patch("workoutbridge.cli.GarminProvider.connect") as connect:
            self.assertEqual(self.call(self.publish_args(plan) + ["--apply"])[0], 2)
        connect.assert_not_called()

    def test_altered_review_does_not_authenticate(self):
        plan = self.plan()
        plan["items"][0]["event"]["description"] = "Run 45 min"
        with patch("workoutbridge.cli.GarminProvider.connect") as connect:
            self.assertEqual(
                self.call(self.publish_args(plan) + ["--apply", "--approve", plan["review_hash"]])[
                    0
                ],
                2,
            )
        connect.assert_not_called()

    def test_unresolved_event_in_batch_blocks_before_authentication(self):
        self.ics.write_bytes(
            calendar(
                "UID:unknown\r\nDTSTART;VALUE=DATE:20270105"
                "\r\nSUMMARY:Track\r\nDESCRIPTION:Coach will explain",
            )
        )
        plan = self.plan()
        self.assertTrue(plan["items"][0]["error"])
        with patch("workoutbridge.cli.GarminProvider.connect") as connect:
            self.assertEqual(
                self.call(self.publish_args(plan) + ["--apply", "--approve", plan["review_hash"]])[
                    0
                ],
                2,
            )
        connect.assert_not_called()

    def test_provider_errors_do_not_leak_credentials(self):
        plan = self.plan()
        with patch(
            "workoutbridge.cli.GarminProvider.connect",
            side_effect=RuntimeError("password=synthetic-secret"),
        ):
            code, out, err = self.call(
                self.publish_args(plan) + ["--apply", "--approve", plan["review_hash"]]
            )
        self.assertEqual(code, 2)
        self.assertNotIn("synthetic-secret", out + err)
