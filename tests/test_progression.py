import unittest
from dataclasses import replace

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_finalsurge
from workoutbridge.reviewed import review_progression


class ProgressionTests(unittest.TestCase):
    def event(self, text=None):
        # Synthetic distances and paces, unrelated to a real athlete's calendar.
        return normalize_finalsurge(
            Event(
                "synthetic",
                "progression",
                "",
                "2030-04-03",
                "Run: 4 mile progression",
                text
                or "Workout: Run\n\nPlanned: 6 mi\n\nWarm up 1 miles\n4 mile progression from ~7:40 -> 7:00\nCool down 1 miles",
            )
        )

    def reviewed(self, event=None):
        return review_progression(
            event or self.event(), pace_choice="range", transition_choice="lap"
        )

    def test_explicit_review_preserves_distances_identity_notes_and_native_targets(self):
        original = self.event()
        self.assertIn("error", review_item("123", original))
        event = self.reviewed(original)
        self.assertEqual(
            (event.source, event.uid, event.date), (original.source, original.uid, original.date)
        )
        self.assertIn(original.description, event.description)
        self.assertIn("Added", event.description)
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual([s.kind for s in draft.steps], ["warm_up", "run", "run", "cool_down"])
        self.assertEqual(
            [s.duration for s in draft.steps], [1609.344, None, 4 * 1609.344, 1609.344]
        )
        self.assertEqual(draft.steps[1].unit, "lap_button")
        self.assertAlmostEqual(draft.steps[2].speed_min, 1609.344 / 460)
        self.assertAlmostEqual(draft.steps[2].speed_max, 1609.344 / 420)
        self.assertIn("Progression", draft.steps[2].note)
        garmin = review_item("123", event)
        coros = review_item("coros:us:synthetic", event)
        self.assertNotIn("error", garmin)
        self.assertNotIn("error", coros)
        gsteps = garmin["payload"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(len(gsteps), 4)
        self.assertEqual(gsteps[2]["targetType"]["workoutTargetTypeKey"], "pace.zone")
        self.assertIn("Progression", gsteps[2]["description"])
        sections = coros["payload"]["sections"]
        self.assertEqual(len(sections), 4)
        self.assertEqual(sections[1]["targetType"], 4)
        self.assertEqual(sections[2]["intensityType"], 2)
        self.assertIn("Progression", coros["payload"]["courseDescription"])

    def test_does_not_guess_missing_bookends_or_ignore_extra_instructions(self):
        for text in [
            "4 mile progression from 7:40 -> 7:00",
            "Warm up 1 miles\n4 mile progression from 7:00 -> 7:40\nCool down 1 miles",
            "Warm up 1 miles\n4 mile progression from 7:40 -> 7:00\nCool down 1 miles\nAdd strides",
            "Warm up 0 miles\n4 mile progression from 7:40 -> 7:00\nCool down 1 miles",
            "Warm up 1 miles\n4 mile progression from 7:90 -> 7:00\nCool down 1 miles",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.reviewed(self.event("Workout: Run\n\n" + text))
        for event in [
            replace(self.event(), cancelled=True),
            replace(self.event(), sport="cycling"),
        ]:
            with self.assertRaises(ValueError):
                self.reviewed(event)
        with self.assertRaises(ValueError):
            review_progression(self.event(), pace_choice="guess", transition_choice="lap")
        self.assertTrue(parse("Run 4 miles progression from 7:00 to 7:40/mi").unresolved)
