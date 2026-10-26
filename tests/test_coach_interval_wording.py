import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class CoachIntervalWordingTests(unittest.TestCase):
    def convert(self, text, normalize=normalize_workout, **options):
        event = Event("synthetic", "coach-wording", "", "2032-03-04", "Run: Training", text)
        return normalize(event, distance_unit="mi", **options)

    def test_combined_workout_preserves_distances_targets_and_recoveries(self):
        text = (
            "1 mi + strides; 5 mi at 7:00 pace; 600m jog; "
            "3 x 600m in 2:10-2:15 1:15 JOGS; 1 mi easys"
        )
        for normalize in (normalize_workout, normalize_finalsurge):
            with self.subTest(normalize=normalize.__name__):
                event = self.convert(text, normalize)
                draft = parse(event.prescription)
                self.assertFalse(draft.unresolved)
                groups = [s for s in draft.steps if isinstance(s, Repeat)]
                strides, reps = groups
                self.assertEqual(strides.count, 4)
                self.assertEqual([s.unit for s in strides.steps], ["lap_button", "lap_button"])
                self.assertFalse(strides.skip_last_recovery)
                self.assertIn("default", strides.steps[0].note.lower())
                self.assertIn("count unspecified", strides.steps[0].note.lower())
                self.assertEqual(reps.count, 3)
                self.assertEqual(reps.steps[0].duration, 600)
                self.assertAlmostEqual(reps.steps[0].speed_min, 600 / 135)
                self.assertAlmostEqual(reps.steps[0].speed_max, 600 / 130)
                self.assertEqual(reps.steps[1].duration, 75)
                self.assertEqual(reps.steps[1].label, "jog")
                self.assertTrue(reps.skip_last_recovery)
                self.assertEqual(draft.steps[-1].duration, 1609.344)
                self.assertEqual(draft.steps[-1].label, "easy")
                self.assertIn(text, event.description)
                for account in ("123", "coros:us:synthetic"):
                    self.assertNotIn("error", review_item(account, event))

    def test_missing_stride_count_respects_strict_and_recovery_opt_outs(self):
        for options in ({"coaching_policy": "strict"}, {"recovery_choice": "review"}):
            self.assertTrue(parse(self.convert("strides", **options).prescription).unresolved)
        for text in ("strides for 30 sec", "strides if feeling good", "strides or hills"):
            self.assertTrue(parse(self.convert(text).prescription).unresolved)
        event = self.convert("7 strides")
        self.assertEqual(parse(event.prescription).steps[0].count, 7)
        self.assertNotIn("count unspecified", event.prescription)

    def test_explicit_in_means_elapsed_rep_time_even_with_mile_preference(self):
        event = self.convert("2 x 1 mi in 5:20-5:30 2:00 jogs", coaching_policy="strict")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[0]
        self.assertAlmostEqual(group.steps[0].speed_min, 1609.344 / 330)
        self.assertEqual(group.steps[1].duration, 120)

    def test_malformed_or_extra_interval_instructions_stay_in_review(self):
        for text in (
            "3 x 600m in 2:10-2:15 0:00 JOGS",
            "3 x 600m in 2:15-2:10 1:15 JOGS",
            "3 x 600m in 2:10-2:15 1:75 JOGS",
            "3 x 600m in 2:10-2:15 1:15 JOGS then sprint",
            "strides + 1 mi easys if sore add another mile",
        ):
            with self.subTest(text=text):
                self.assertTrue(parse(self.convert(text).prescription).unresolved)


if __name__ == "__main__":
    unittest.main()
