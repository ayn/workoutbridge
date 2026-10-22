import json
import subprocess
import sys
import unittest

from workoutbridge.parser import parse


class ParserTests(unittest.TestCase):
    def test_units_and_effort(self):
        draft = parse("Warm up 1 mi easy; Run 600 m hard; Cool down 5 min")
        self.assertEqual([s.duration for s in draft.steps], [1609.344, 600, 300])
        self.assertEqual(draft.steps[1].label, "hard")
        self.assertTrue(draft.requires_review)
        self.assertFalse(draft.unresolved)

    def test_lap(self):
        self.assertEqual(parse("Run until lap").steps[0].unit, "lap_button")

    def test_no_invented_steps(self):
        self.assertEqual(len(parse("Run 15 min easy").steps), 1)

    def test_unknown_repeats_are_not_partially_parsed(self):
        text = "4 x 200 m in 62-64 sec; 2 min walk/jog recovery"
        draft = parse(text)
        self.assertFalse(draft.steps)
        self.assertEqual(len(draft.unresolved), 2)
        self.assertEqual(draft.original_text, text)

    def test_explicit_easy_run_is_not_rest(self):
        step = parse("Run 2 min easy").steps[0]
        self.assertEqual(step.kind, "run")

    def test_invalid_duration(self):
        for text in ("Run 0 min", "Run -2 min", "Run nan min"):
            with self.subTest(text=text):
                self.assertTrue(parse(text).unresolved)

    def test_trailing_instructions_not_dropped(self):
        self.assertTrue(parse("Run 15 min unless injured").unresolved)

    def test_blank(self):
        self.assertTrue(parse(" ; ").unresolved)

    def test_cli(self):
        for text, code in (("Run 10 min", 0), ("unknown", 2)):
            result = subprocess.run(
                [sys.executable, "-m", "workoutbridge.cli"],
                input=text,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, code)
            self.assertTrue(json.loads(result.stdout)["requires_review"])


class TimedStridesTests(unittest.TestCase):
    def test_timed_strides_keep_duration_count_and_lap_recovery(self):
        draft = parse("Run 8 min easy; 4 x 12 sec strides with lap recovery")
        self.assertFalse(draft.unresolved)
        repeat = draft.steps[1]
        self.assertEqual(repeat.count, 4)
        self.assertTrue(repeat.skip_last_recovery)
        self.assertEqual(repeat.steps[0].duration, 12)
        self.assertEqual(repeat.steps[0].unit, "seconds")
        self.assertEqual(repeat.steps[0].note, "Strides")
        self.assertEqual(repeat.steps[1].unit, "lap_button")


class DistanceUnitsTests(unittest.TestCase):
    def test_prescribed_distance_units_survive_internal_meter_conversion(self):
        draft = parse(
            "Warm up 1.25 miles; 3 x 0.8 km in 200-220 with 60 sec easy recovery; Run 400 m; Cool down 1.5 km"
        )
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].display_unit, "mi")
        self.assertEqual(draft.steps[1].steps[0].display_unit, "km")
        self.assertIsNone(draft.steps[1].steps[1].display_unit)
        self.assertEqual(draft.steps[2].display_unit, "m")
        self.assertEqual(draft.steps[3].display_unit, "km")
        self.assertEqual(draft.steps[0].duration, 1.25 * 1609.344)
        self.assertEqual(draft.steps[1].steps[0].duration, 800)
        self.assertEqual(draft.steps[3].duration, 1500)
        lap = parse("3 x 0.5 km smooth with lap recovery").steps[0]
        self.assertEqual(lap.steps[0].display_unit, "km")
        self.assertIsNone(lap.steps[1].display_unit)
        cycling = parse("Ride 18 km easy", sport="cycling").steps[0]
        self.assertEqual(cycling.display_unit, "km")
        progression = parse("Run 4 miles progression from 7:40 to 7:00/mi").steps[0]
        self.assertEqual(progression.display_unit, "mi")

    def test_display_metadata_preserves_existing_provider_approvals(self):
        from workoutbridge.calendar import Event
        from workoutbridge.cli import review_item

        event = Event(
            "synthetic",
            "units",
            "",
            "2030-05-01",
            "Synthetic mixed units",
            "Warm up 1.25 miles; 3 x 0.8 km in 200-220 with 60 sec easy recovery; Run 400 m; Cool down 1.5 km",
        )
        # Captured before adding display metadata; includes each provider's payload.
        for account, approved in [
            ("123", "f9f4478961cf8ffde3e5e5d1dd1a00d5c6184cde384b371fcdcbb7be889fc430"),
            (
                "coros:us:synthetic",
                "2e157c359ddd17a1f3a36972f77a8d16fd7ff98f2acbd08c4bc692af58d6b44b",
            ),
        ]:
            self.assertEqual(review_item(account, event)["approval"], approved)
