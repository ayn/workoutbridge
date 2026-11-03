import unittest
from unittest.mock import Mock

from workoutbridge.ai import Interpreter
from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import event_values
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout
from workoutbridge.publishing import event_payload


class RestDayTests(unittest.TestCase):
    def event(self, title="Rest Day", description="Workout: Rest Day"):
        return Event("synthetic", "rest", "", "2030-04-01", title, description)

    def test_explicit_rest_days_are_visible_without_publication_or_review(self):
        for normalize in (normalize_finalsurge, normalize_workout):
            for title, description in (
                ("Rest Day", "Workout: Rest Day"),
                (" rest day ", ""),
                ("REST DAY", "Workout: Rest Day\n\nPlanned: 0 mi"),
                ("rest and recovery", ""),
            ):
                event = normalize(self.event(title, description))
                for account in ("123", "coros:us:synthetic"):
                    with self.subTest(normalize=normalize.__name__, title=title, account=account):
                        item = review_item(account, event)
                        self.assertEqual(item.get("skipped"), "rest_day")
                        self.assertEqual(item["error"], "Not published — rest day")
                        self.assertFalse(item["draft"]["requires_review"])
                        self.assertEqual(item["draft"]["unresolved"], [])
                        self.assertNotIn("payload", item)
                        self.assertNotIn("approval", item)
                for build in (event_payload, event_values):
                    with self.assertRaisesRegex(ValueError, "rest day"):
                        build(event)

    def test_rest_mentions_and_substantive_instructions_are_not_silently_skipped(self):
        for event in (
            self.event("Run: 5 km after rest day", "Run 5 km"),
            self.event("Run: intervals", "Run 4 x 400 m with 1 min rest recovery"),
            self.event("Rest Day", "Workout: Rest Day\nRun 5 km if feeling better"),
            self.event("Rest Day or easy run", ""),
        ):
            self.assertNotIn("skipped", review_item("123", normalize_workout(event)))

    def test_rest_days_do_not_request_ai_interpretation(self):
        item = review_item("123", normalize_finalsurge(self.event()))
        engine = Mock(spec=Interpreter)
        Interpreter.observe_plan(engine, {"items": [item]})
        engine.database.assert_not_called()
        engine.interpret.assert_not_called()
