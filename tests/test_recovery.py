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

    def test_unknown_error_and_arbitrary_review_text_are_redacted(self):
        from workoutbridge.publishing import ReviewRequired

        for error in (RuntimeError("PRIVATE"), ReviewRequired("PRIVATE")):
            result = publication_failure(
                error, None, "2030-01-01T00:00:00+00:00", "publish_and_verify"
            )
            self.assertIsNone(result["next_retry"])
            self.assertNotIn("PRIVATE", str(result))
