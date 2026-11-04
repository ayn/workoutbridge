import importlib.util
import unittest

from workoutbridge.recovery import publication_failure


class RecoveryTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("garminconnect"), "optional Garmin SDK")
    def test_sdk_connection_and_rate_limit_errors_retry_but_authentication_does_not(self):
        from garminconnect import (
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        )

        for error, retry in (
            (GarminConnectConnectionError("PRIVATE"), True),
            (GarminConnectTooManyRequestsError("PRIVATE"), True),
            (GarminConnectAuthenticationError("PRIVATE"), False),
        ):
            result = publication_failure(error, None, "2030-01-01T00:00:00+00:00", "connect")
            self.assertEqual(bool(result["next_retry"]), retry)
            self.assertNotIn("PRIVATE", str(result))

    @unittest.skipUnless(importlib.util.find_spec("requests"), "optional Requests transport")
    def test_http_status_and_error_type_are_saved_without_provider_text(self):
        import requests

        for status, code, retry in (
            (429, "provider_unavailable", True),
            (503, "provider_unavailable", True),
            (401, "provider_authentication", False),
            (403, "provider_authentication", False),
            (404, "destination_not_found", False),
        ):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                error = requests.HTTPError("PRIVATE bearer token and URL", response=response)
                failure = publication_failure(
                    error, None, "2030-01-01T00:00:00+00:00", "publish_and_verify"
                )
                self.assertEqual(failure["code"], code)
                self.assertEqual(failure["http_status"], status)
                self.assertEqual(failure["exception_type"], "HTTPError")
                self.assertEqual(bool(failure["next_retry"]), retry)
                self.assertNotIn("PRIVATE", str(failure))

    def test_known_schedule_and_identity_guards_keep_their_specific_reason(self):
        from workoutbridge.publishing import ReviewRequired

        for reason in (
            "Previously scheduled entry is absent; reconcile manually",
            "Recorded destination identity is missing; refusing overwrite",
            "Multiple destination workouts have this identity",
        ):
            failure = publication_failure(
                ReviewRequired(reason), None, "2030-01-01T00:00:00+00:00", "publish_and_verify"
            )
            self.assertEqual(failure["message"], reason)
            self.assertEqual(failure["exception_type"], "ReviewRequired")
            self.assertIsNone(failure["next_retry"])

    def test_unknown_error_and_arbitrary_review_text_are_redacted(self):
        from workoutbridge.publishing import ReviewRequired

        for error in (RuntimeError("PRIVATE"), ReviewRequired("PRIVATE")):
            result = publication_failure(
                error, None, "2030-01-01T00:00:00+00:00", "publish_and_verify"
            )
            self.assertIsNone(result["next_retry"])
            self.assertNotIn("PRIVATE", str(result))
