import unittest
from unittest.mock import Mock

from workoutbridge.ai import Interpreter
from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import event_values
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout
from workoutbridge.publishing import event_payload


class CalendarBlockTests(unittest.TestCase):
    def test_bare_busy_entries_are_visible_but_not_workouts(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            event = normalize(Event("synthetic", "busy", "", "2030-04-01", "Busy", ""))
            for account in ("123", "coros:us:synthetic"):
                item = review_item(account, event)
                self.assertEqual(item.get("skipped"), "calendar_block")
                self.assertFalse(item["draft"]["requires_review"])
                self.assertNotIn("payload", item)
                engine = Mock(spec=Interpreter)
                Interpreter.observe_plan(engine, {"items": [item]})
                engine.interpret.assert_not_called()
            for provider in (event_payload, event_values):
                with self.assertRaisesRegex(ValueError, "calendar block"):
                    provider(event)

    def test_busy_title_does_not_hide_a_substantive_prescription(self):
        event = normalize_workout(
            Event("synthetic", "busy-run", "", "2030-04-01", "Busy", "Run 8 km easy")
        )
        self.assertNotIn("error", review_item("123", event))
