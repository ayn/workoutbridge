import io
import unittest
from unittest.mock import MagicMock, patch

from workoutbridge.feed import read_calendar


class FeedTests(unittest.TestCase):
    def test_https_bounded_read_and_timeout(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"BEGIN:VCALENDAR"
        with patch("workoutbridge.feed.build_opener") as build:
            build.return_value.open.return_value = response
            self.assertEqual(read_calendar("https://example.invalid/feed.ics"), b"BEGIN:VCALENDAR")
            self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 30)
            response.read.assert_called_once_with(2_000_001)

    def test_oversized_feed_rejected(self):
        with patch("workoutbridge.feed.build_opener") as build:
            build.return_value.open.return_value = io.BytesIO(b"x" * 2_000_001)
            with self.assertRaises(ValueError):
                read_calendar("https://example.invalid/feed.ics")

    def test_unsafe_urls_rejected_before_network(self):
        for url in (
            "http://example.invalid/feed",
            "ftp://example.invalid/feed",
            "https://user:password@example.invalid/feed",
            "https:///missing",
        ):
            with self.subTest(url=url), patch("workoutbridge.feed.build_opener") as build:
                with self.assertRaises(ValueError):
                    read_calendar(url)
                build.assert_not_called()

    def test_redirects_rejected(self):
        from workoutbridge.feed import NoRedirect

        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "http://other"))
