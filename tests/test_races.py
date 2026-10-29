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

    def test_official_calendar_requires_both_name_and_date(self):
        from dataclasses import replace

        for title, day in (
            ("Run: CIM", "2026-12-06"),
            ("Run: Big Sur", "2027-04-25"),
            ("Run: Grandma's", "2027-06-19"),
            ("Run: NYC", "2026-11-01"),
            ("Run: Christmas Relays", "2026-12-20"),
            ("Run: Tamalpa Marin Memorial 5-Mile", "2026-05-25"),
            ("Run: Stow Lake Stampede 5K", "2026-04-19"),
        ):
            event = replace(self.event(title), date=day)
            self.assertEqual(review_item("123", event).get("skipped"), "race")
            self.assertNotIn("skipped", review_item("123", replace(event, date="2030-01-01")))
        for title in ("Run: CIM pace intervals", "Run: Big Sur training", "Run: 8 miles"):
            self.assertNotIn(
                "skipped", review_item("123", replace(self.event(title), date="2026-12-06"))
            )

    def test_skipped_races_do_not_request_ai_interpretation(self):
        engine = Mock(spec=Interpreter)
        Interpreter.observe_plan(
            engine, {"items": [{"skipped": "race", "error": "Not published — race", "event": {}}]}
        )
        engine.database.assert_not_called()
        engine.interpret.assert_not_called()
