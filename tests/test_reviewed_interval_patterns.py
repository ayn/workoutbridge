import unittest

from workoutbridge.calendar import Event
from workoutbridge.coros import workout_payload as coros_payload
from workoutbridge.garmin import workout_payload as garmin_payload
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class ReviewedIntervalPatternsTests(unittest.TestCase):
    def event(self, text, **options):
        return normalize_workout(
            Event("synthetic", "reviewed", "", "2030-01-01", "Run: " + text, ""), **options
        )

    def test_distance_recovery_has_exact_elapsed_pace_bounds_and_note(self):
        for text in (
            "4x800m at 3:10-3:15 w/ 200m jog in 75-90s",
            "4x800m at 3:10-3:15 (200m jog in 75-90s)",
        ):
            event = self.event(text)
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved, text)
            group = draft.steps[0]
            self.assertIsInstance(group, Repeat)
            self.assertEqual(group.count, 4)
            self.assertTrue(group.skip_last_recovery)
            recovery = group.steps[-1]
            self.assertEqual(
                (recovery.kind, recovery.duration, recovery.unit), ("rest", 200, "meters")
            )
            self.assertAlmostEqual(recovery.speed_min, 200 / 90)
            self.assertAlmostEqual(recovery.speed_max, 200 / 75)
            self.assertIn("75-90s", recovery.note)
            garmin = garmin_payload("Synthetic", event.description, draft)["workoutSegments"][0][
                "workoutSteps"
            ][0]["workoutSteps"][1]
            self.assertEqual(garmin["stepType"]["stepTypeKey"], "recovery")
            self.assertEqual(garmin["endConditionValue"], 200)
            self.assertAlmostEqual(garmin["targetValueOne"], 200 / 90)
            coros = coros_payload("Synthetic", event.description, draft)["sections"][0]["sets"][1]
            self.assertEqual(
                (coros["sectionType"], coros["targetType"], coros["targetValue"]), (3, 1, 200)
            )
            self.assertEqual((coros["intensityValueStart"], coros["intensityValueEnd"]), (375, 450))

    def test_continuous_distance_recovery_keeps_final_recovery_and_after_set_rest(self):
        event = self.event("4x (300m fast; 100m jog in 30-35s)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertFalse(draft.steps[0].skip_last_recovery)
        self.assertEqual(draft.steps[0].steps[-1].duration, 100)
        event = self.event("4x800m at 3:10-3:15 w/ 200m jog in 75-90s (4:00 rest after set)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertTrue(draft.steps[0].skip_last_recovery)
        self.assertEqual((draft.steps[1].kind, draft.steps[1].duration), ("rest", 240))

    def test_elapsed_targets_on_both_sides_of_a_continuous_cycle(self):
        event = self.event("5x (300m at 63-65; 100m jog in 30s)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[0]
        self.assertFalse(group.skip_last_recovery)
        self.assertAlmostEqual(group.steps[0].speed_min, 300 / 65)
        self.assertAlmostEqual(group.steps[0].speed_max, 300 / 63)
        self.assertAlmostEqual(group.steps[1].speed_min, 100 / 30)
        self.assertAlmostEqual(group.steps[1].speed_max, 100 / 30)
        for compiler in (garmin_payload, coros_payload):
            compiler("Synthetic", event.description, draft)
        event = self.event("4x300m fast w/ 100m jog in 30-35s")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertTrue(draft.steps[0].skip_last_recovery)
        self.assertIsNone(draft.steps[0].steps[0].speed_min)

    def test_larger_rep_count_preserves_range_and_respects_strict(self):
        for text, count in (
            ("8-9x600m at 2:10-2:15 (2 min rest)", 9),
            ("3-5x (3 min hard; 3 min moderate)", 5),
        ):
            event = self.event(text)
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[0].count, count)
            self.assertIn(text, event.description)
            self.assertIn("Repetition range", event.description)
            self.assertTrue(
                parse(self.event(text, coaching_policy="strict").prescription).unresolved
            )
        for text in ("0-4x800m", "4-101x800m", "8-6x800m", "4-6x choose a workout"):
            self.assertTrue(parse(self.event(text).prescription).unresolved)

    def test_one_sided_pace_has_approved_band_and_original_limit_note(self):
        for text, unit, limit, width in (
            ("1 mile at 6:15/mi or faster", "mi", 375, 45),
            ("1 mile fast sub 6:15", "mi", 375, 45),
            ("2 km at under 4:00/km", "km", 240, 28),
        ):
            event = self.event(text)
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved, text)
            step = draft.steps[0]
            factor = 1609.344 if unit == "mi" else 1000
            self.assertAlmostEqual(step.speed_min, factor / limit)
            self.assertAlmostEqual(step.speed_max, factor / (limit - width))
            self.assertIn("or faster", step.note)
            self.assertIn(text, event.description)
            self.assertTrue(
                parse(self.event(text, coaching_policy="strict").prescription).unresolved
            )
            for compiler in (garmin_payload, coros_payload):
                compiler("Synthetic", event.description, draft)

    def test_relative_effort_stays_a_note_without_numeric_pace(self):
        event = self.event("3 miles faster than marathon effort")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertIsNone(draft.steps[0].speed_min)
        result = garmin_payload("Synthetic", event.description, draft)
        self.assertIn(
            "faster than marathon effort",
            result["workoutSegments"][0]["workoutSteps"][0]["description"],
        )

    def test_invalid_elapsed_recoveries_and_unknown_tails_stay_review(self):
        for text in (
            "4x800m at 3:10-3:15 w/ 200m jog in 0-90s",
            "4x800m at 3:10-3:15 w/ 200m jog in 90-75s",
            "4x800m at 3:10-3:15 w/ 200m jog in 75-90s then add a set",
            "4x800m at 3:10-3:15 w/ 200m jog in 75-90s (if slow add rest)",
            "1 mile at under 0:30/mi",
            "1 mile at under 6:15/mi or cross train",
        ):
            self.assertTrue(parse(self.event(text).prescription).unresolved, text)
