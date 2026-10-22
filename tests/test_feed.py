import base64
import io
import unittest
from unittest.mock import MagicMock, patch

from workoutbridge.feed import calendar_feed_url, read_calendar


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


class GoogleCalendarLinkTests(unittest.TestCase):
    def test_public_browser_and_embed_links_use_public_ics(self):
        calendar = "synthetic@example.invalid"
        cid = base64.urlsafe_b64encode(calendar.encode()).decode().rstrip("=")
        expected = (
            "https://calendar.google.com/calendar/ical/synthetic%40example.invalid/public/basic.ics"
        )
        for url in (
            "https://calendar.google.com/calendar/u/0?cid=" + cid,
            "https://calendar.google.com/calendar/u/0/r?cid=" + cid,
            "https://calendar.google.com/calendar/embed?src=synthetic%40example.invalid&ctz=UTC",
        ):
            with self.subTest(url=url), patch("workoutbridge.feed.build_opener") as build:
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = b"BEGIN:VCALENDAR"
                build.return_value.open.return_value = response
                read_calendar(url)
                self.assertEqual(build.return_value.open.call_args.args[0].full_url, expected)

    def test_existing_secret_and_public_ics_urls_are_preserved(self):
        for url in (
            "https://calendar.google.com/calendar/ical/synthetic%40example.invalid/private-SYNTHETIC/basic.ics",
            "https://calendar.google.com/calendar/ical/synthetic%40example.invalid/public/basic.ics",
        ):
            with patch("workoutbridge.feed.build_opener") as build:
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = b"BEGIN:VCALENDAR"
                build.return_value.open.return_value = response
                read_calendar(url)
                self.assertEqual(build.return_value.open.call_args.args[0].full_url, url)

    def test_google_page_without_one_valid_calendar_is_rejected_before_fetch(self):
        for url in (
            "https://calendar.google.com/calendar/u/0/r",
            "https://calendar.google.com/calendar/u/0?cid=invalid",
            "https://calendar.google.com/calendar/embed?src=one%40example.invalid&src=two%40example.invalid",
            "https://calendar.google.com/calendar/embed?src=https%3A%2F%2F127.0.0.1%2Fsecret",
        ):
            with self.subTest(url=url), patch("workoutbridge.feed.build_opener") as build:
                with self.assertRaisesRegex(ValueError, "iCal"):
                    read_calendar(url)
                build.assert_not_called()


class ICloudCalendarLinkTests(unittest.TestCase):
    def test_webcal_and_https_published_links_use_https(self):
        expected = "https://p123-caldav.icloud.com/published/2/SYNTHETIC_abc-123"
        for url in (expected, expected.replace("https:", "webcal:")):
            with self.subTest(url=url), patch("workoutbridge.feed.build_opener") as build:
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = b"BEGIN:VCALENDAR"
                build.return_value.open.return_value = response
                self.assertEqual(calendar_feed_url(url), expected)
                self.assertEqual(read_calendar(url), b"BEGIN:VCALENDAR")
                self.assertEqual(build.return_value.open.call_args.args[0].full_url, expected)

    def test_non_public_or_unsafe_icloud_links_rejected_before_fetch(self):
        for url in (
            "http://p123-caldav.icloud.com/published/2/SYNTHETIC",
            "https://user:secret@p123-caldav.icloud.com/published/2/SYNTHETIC",
            "https://p123-caldav.icloud.com:444/published/2/SYNTHETIC",
            "https://p123-caldav.icloud.com/published/2/SYNTHETIC#fragment",
            "https://p123-caldav.icloud.com/published/2/SYNTHETIC?query=1",
            "https://p123-caldav.icloud.com/private/calendar/",
            "https://p123-caldav.icloud.com/published/2/../private",
        ):
            with self.subTest(url=url), patch("workoutbridge.feed.build_opener") as build:
                with self.assertRaises(ValueError):
                    read_calendar(url)
                build.assert_not_called()
