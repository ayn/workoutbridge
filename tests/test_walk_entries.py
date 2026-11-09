import unittest
from unittest.mock import Mock

from workoutbridge.ai import Interpreter
from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import event_values
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout
from workoutbridge.publishing import event_payload


class WalkEntryTests(unittest.TestCase):
    def test_explicit_walk_metadata_is_skipped_without_ai_or_provider_payload(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            event = normalize(
                Event(
                    "synthetic",
                    "walk",
                    "",
                    "2030-04-01",
                    "Walk",
                    "Workout: Walk",
                    sport="unsupported",
                )
            )
            for account in ("123", "coros:us:synthetic"):
                item = review_item(account, event)
                self.assertEqual(item.get("skipped"), "walk")
                self.assertFalse(item["draft"]["requires_review"])
                self.assertEqual(item["draft"]["unresolved"], [])
                self.assertNotIn("payload", item)
                engine = Mock(spec=Interpreter)
                Interpreter.observe_plan(engine, {"items": [item]})
                engine.interpret.assert_not_called()
            for provider in (event_payload, event_values):
                with self.assertRaisesRegex(ValueError, "walk"):
                    provider(event)

    def test_walk_title_does_not_hide_prescribed_running(self):
        for event in (
            Event("synthetic", "run", "", "2030-04-01", "Walk", "Run 8 km easy"),
            Event("synthetic", "run", "", "2030-04-01", "Run: walk recovery", "Workout: Run"),
            Event(
                "synthetic",
                "run",
                "",
                "2030-04-01",
                "Walk",
                "Workout: Walk",
                structured_text="Run 8 km easy",
            ),
            Event("synthetic", "run", "", "2030-04-01", "Run: easy", "Workout: Walk"),
            Event("synthetic", "run", "", "2030-04-01", "Walk", "Workout: Walk\nWorkout: Run"),
            Event("synthetic", "run", "", "2030-04-01", "Walk", "Workout: Walk\nRun 8 km easy"),
            Event(
                "synthetic",
                "run",
                "",
                "2030-04-01",
                "Walk",
                "Workout: Walk\n[WorkoutBridge]\nRun 8 km easy\n[/WorkoutBridge]",
            ),
        ):
            self.assertNotEqual(review_item("123", event).get("skipped"), "walk")

    def test_bare_walks_are_explicitly_non_workouts(self):
        for title in ("Walk", "Walking"):
            item = review_item("123", Event("synthetic", "walk", "", "2030-04-01", title, ""))
            self.assertEqual(item.get("skipped"), "walk")
