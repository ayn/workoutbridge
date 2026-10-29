import unittest
from unittest.mock import Mock

from workoutbridge.ai import Interpreter
from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import event_values
from workoutbridge.publishing import event_payload


class RaceTests(unittest.TestCase):
    def event(self, title, description="Workout: Run", structured="Run 8 km"):
        return Event(
            "synthetic", "race", "", "2030-04-01", title, description, structured_text=structured
        )

    def test_races_are_visible_but_cannot_be_published_to_either_provider(self):
        for title, description in (
            ("Run - Race: Spring road event", "Workout: Run - Race"),
            ("Run - Easy: Coastal Half Marathon", "Workout: Run - Easy"),
            ("Race: Park 8K", "Workout: Run"),
        ):
            event = self.event(title, description)
            for account in ("123", "coros:us:synthetic"):
                item = review_item(account, event)
                self.assertEqual(item.get("skipped"), "race")
                self.assertEqual(item["error"], "Not published — race")
                self.assertNotIn("payload", item)
                self.assertNotIn("approval", item)
            for build in (event_payload, event_values):
                with self.assertRaisesRegex(ValueError, "race"):
                    build(event)

    def test_race_pace_training_is_not_skipped(self):
        for title in (
            "Run: HMP race pace",
            "Run: Half marathon pace intervals",
            "Run: Marathon training",
            "Run: Pre-race easy run",
        ):
            self.assertNotIn("error", review_item("123", self.event(title)))

    def test_skipped_races_do_not_request_ai_interpretation(self):
        engine = Mock(spec=Interpreter)
        Interpreter.observe_plan(
            engine, {"items": [{"skipped": "race", "error": "Not published — race", "event": {}}]}
        )
        engine.database.assert_not_called()
        engine.interpret.assert_not_called()
