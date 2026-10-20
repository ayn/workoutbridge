import unittest
from pathlib import Path
from unittest.mock import Mock

from workoutbridge.garmin import GarminProvider


class GarminAdapterTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.profile_id = 12345
        return client

    def test_account_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            GarminProvider(self.client(), expected_account="67890")

    def test_missing_stable_identity_rejected(self):
        client = self.client()
        client.profile_id = None
        with self.assertRaises(ValueError):
            GarminProvider(client, expected_account="12345")

    def test_session_login_no_password_or_new_account_link(self):
        client = self.client()
        provider = GarminProvider.connect(
            Path("/synthetic/session"),
            expected_account="12345",
            client_factory=lambda: client,
        )
        client.login.assert_called_once_with("/synthetic/session")
        self.assertEqual(provider.account_id, "12345")

    def test_complete_pagination(self):
        client = self.client()
        client.get_workouts.side_effect = [
            [{"workoutId": i} for i in range(1, 101)],
            [{"workoutId": 101}],
        ]
        provider = GarminProvider(client, expected_account="12345")
        self.assertEqual(len(provider.list_workouts()), 101)
        self.assertEqual(client.get_workouts.call_args_list[1].args, (100, 100))

    def test_incomplete_or_malformed_enumeration_fails_closed(self):
        client = self.client()
        client.get_workouts.return_value = [{"workoutId": i} for i in range(1, 101)]
        provider = GarminProvider(client, expected_account="12345", max_pages=1)
        with self.assertRaises(ValueError):
            provider.list_workouts()
        client.get_workouts.return_value = {"error": "unexpected"}
        with self.assertRaises(ValueError):
            provider.list_workouts()
        client.get_calendar_week.return_value = {}
        with self.assertRaises(ValueError):
            provider.list_schedule("2027-01-05")

    def test_mapping_to_existing_library_methods(self):
        client = self.client()
        provider = GarminProvider(client, expected_account="12345")
        client.upload_workout.return_value = {"workoutId": 22}
        client.get_calendar_week.return_value = {
            "calendarItems": [
                {"workoutId": 22, "date": "2027-01-05"},
                {"workoutId": 99, "date": "2027-01-06"},
            ]
        }
        self.assertEqual(provider.upload({"workoutName": "Synthetic"}), "22")
        provider.get_workout("22")
        client.get_workout_by_id.assert_called_once_with("22")
        provider.update("22", {"workoutName": "Changed"})
        client.update_workout.assert_called_once_with("22", {"workoutName": "Changed"})
        provider.schedule("22", "2027-01-05")
        client.schedule_workout.assert_called_once_with("22", "2027-01-05")
        self.assertEqual(len(provider.list_schedule("2027-01-05")), 1)

    def test_invalid_upload_response_fails_closed(self):
        client = self.client()
        client.upload_workout.return_value = {}
        with self.assertRaises(ValueError):
            GarminProvider(client, expected_account="12345").upload({})

    def test_malformed_scheduled_workout_cannot_look_like_empty_calendar(self):
        client = self.client()
        provider = GarminProvider(client, expected_account="12345")
        client.get_calendar_week.return_value = {"calendarItems": [{"workoutId": 22}]}
        with self.assertRaises(ValueError):
            provider.list_schedule("2027-01-05")
