import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import approval_token
from workoutbridge.publishing import digest


class CorosEventTests(unittest.TestCase):
    def test_review_uses_coros_payload_and_exact_account_approval(self):
        event = Event("synthetic", "run", "", "2026-10-22", "Easy run", "run 15 min")
        item = review_item("coros:us:synthetic", event)
        self.assertEqual(item["payload"]["sportType"], 1)
        self.assertEqual(
            item["approval"],
            approval_token(
                "coros:us:synthetic",
                source=event.source,
                uid=digest([event.uid, event.recurrence_id]),
                day=event.date,
                course=item["payload"],
            ),
        )

    def test_cancelled_coros_event_requires_review(self):
        event = Event("synthetic", "run", "", "2026-10-22", "Run", "run 15 min", cancelled=True)
        self.assertIn("error", review_item("coros:us:synthetic", event))
