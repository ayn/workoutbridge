import unittest

from workoutbridge.garmin import workout_payload
from workoutbridge.parser import parse


class IntervalTests(unittest.TestCase):
    def test_explicit_repeats_pace_and_recovery(self):
        draft = parse(
            "Warm up until lap; "
            "4 x 200 m in 62-64 sec with 2 min walk/jog recovery; "
            "Cool down 5 min"
        )
        self.assertFalse(draft.unresolved)
        repeat = draft.steps[1]
        self.assertEqual(repeat.count, 4)
        self.assertTrue(repeat.skip_last_recovery)
        run, recovery = repeat.steps
        self.assertEqual(run.note, "1:02-1:04")
        self.assertAlmostEqual(run.speed_min, 200 / 64)
        self.assertAlmostEqual(run.speed_max, 200 / 62)
        self.assertEqual(recovery.duration, 120)
        self.assertEqual(recovery.label, "walk/jog")

    def test_clock_times(self):
        draft = parse("3 x 400 m in 2:04-2:08 with 3 min easy recovery")
        self.assertFalse(draft.unresolved)
        run, recovery = draft.steps[0].steps
        self.assertEqual(run.note, "2:04-2:08")
        self.assertEqual(recovery.kind, "run")
        self.assertAlmostEqual(run.speed_min, 400 / 128)

    def test_no_implicit_recovery(self):
        self.assertTrue(parse("4 x 200 m in 62-64 sec").unresolved)

    def test_invalid_ranges_or_counts(self):
        for text in (
            "4 x 200 m in 64-62 sec with 2 min easy recovery",
            "0 x 200 m in 62-64 sec with 2 min easy recovery",
            "1000 x 200 m in 62-64 sec with 2 min easy recovery",
            "4 x 0 m in 62-64 sec with 2 min easy recovery",
            "4 x 200 m in 0-64 sec with 2 min easy recovery",
        ):
            with self.subTest(text=text):
                self.assertTrue(parse(text).unresolved)

    def test_garmin_native_repeat_and_no_invented_targets(self):
        draft = parse("Warm up until lap; 4 x 200 m in 62-64 sec with 2 min walk/jog recovery")
        payload = workout_payload("Track", "Original instructions", draft)
        self.assertEqual(payload["workoutName"], "Track")
        self.assertEqual(payload["description"], "Original instructions")
        steps = payload["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[0]["endCondition"]["conditionTypeKey"], "lap.button")
        self.assertEqual(steps[0]["targetType"]["workoutTargetTypeKey"], "no.target")
        repeat = steps[1]
        self.assertEqual(repeat["type"], "RepeatGroupDTO")
        self.assertEqual(repeat["numberOfIterations"], 4)
        self.assertTrue(repeat["skipLastRestStep"])
        run = repeat["workoutSteps"][0]
        self.assertEqual(run["description"], "1:02-1:04")
        self.assertAlmostEqual(run["targetValueOne"], 200 / 64)
        self.assertAlmostEqual(run["targetValueTwo"], 200 / 62)

    def test_unresolved_draft_cannot_be_exported(self):
        with self.assertRaises(ValueError):
            workout_payload("Bad", "", parse("Run 10 min; do something"))

    def test_nonfinite_interval_is_unresolved(self):
        huge = "9" * 400
        self.assertTrue(parse(f"4 x {huge} m in 62-64 sec with 2 min easy recovery").unresolved)
