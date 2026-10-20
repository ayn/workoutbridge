import contextlib
import io
import json
import logging
import unittest
from unittest.mock import Mock, patch

from workoutbridge.cli import main
from workoutbridge.garmin import GarminProvider


class GarminCheckTests(unittest.TestCase):
    def run_check(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(
                [
                    "garmin-check",
                    "--account-id",
                    "12345",
                    "--session-dir",
                    "/synthetic/session",
                    "--date",
                    "2027-01-05",
                ]
            )
        return code, output.getvalue(), errors.getvalue()

    @patch("workoutbridge.cli.GarminProvider.connect")
    def test_check_reads_destination_without_mutating_it(self, connect):
        client = Mock(profile_id=12345)
        client.get_workouts.return_value = [{"workoutId": 22}]
        client.get_calendar_week.return_value = {
            "calendarItems": [{"workoutId": 22, "date": "2027-01-05"}]
        }
        connect.return_value = GarminProvider(client, expected_account="12345")
        code, output, errors = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(
            json.loads(output),
            {
                "status": "read-access-verified",
                "account_id": "12345",
                "date": "2027-01-05",
                "workouts": 1,
                "scheduled_workouts": 1,
            },
        )
        self.assertEqual(
            [call[0] for call in client.method_calls],
            ["get_workouts", "get_calendar_week"],
        )

    @patch("workoutbridge.cli.GarminProvider.connect")
    def test_auth_failure_is_redacted_and_logging_restored(self, connect):
        def fail(*args, **kwargs):
            logging.error("synthetic-secret")
            raise ValueError("synthetic-secret")

        connect.side_effect = fail
        before = logging.root.manager.disable
        code, output, errors = self.run_check()
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertNotIn("synthetic-secret", errors)
        self.assertIn("No workouts were changed", errors)
        self.assertEqual(logging.root.manager.disable, before)

    @patch("workoutbridge.cli.GarminProvider.connect")
    def test_incomplete_enumeration_does_not_report_success(self, connect):
        client = Mock(profile_id=12345)
        client.get_workouts.return_value = {"unexpected": []}
        connect.return_value = GarminProvider(client, expected_account="12345")
        code, output, _ = self.run_check()
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        client.get_calendar_week.assert_not_called()
