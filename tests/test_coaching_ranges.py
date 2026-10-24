import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class CoachingRangeTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "ranges", "", "2030-02-01", "Run: " + text, "")

    def test_distance_range_uses_upper_bound_with_original_range_on_the_step(self):
        for text, expected, note in (
            ("5-6 miles easy", 6 * 1609.344, "5-6 miles"),
            ("10–12 km easy", 12000, "10–12 km"),
        ):
            self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)
            event = normalize_workout(self.event(text), coaching_policy="cj")
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[0].duration, expected)
            self.assertEqual(draft.steps[0].note, note)
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_recovery_range_uses_longer_time_with_range_on_recovery_only(self):
        text = "4x800m at 2:55-3:00 (2:30-3:00 rest)"
        self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)
        event = normalize_workout(self.event(text), coaching_policy="cj")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        work, rest = draft.steps[0].steps
        self.assertEqual(rest.duration, 180)
        self.assertEqual(rest.note, "2:30-3:00 rest")
        self.assertNotIn("2:30-3:00 rest", work.note)

    def test_minute_range_after_tempo_retains_the_original_recovery_note(self):
        event = normalize_workout(
            self.event("3 miles tempo at 6:30-6:40/mi (5-7 mins rest)"), coaching_policy="cj"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[1].duration, 420)
        self.assertEqual(draft.steps[1].note, "5-7 mins rest")

    def test_range_policy_does_not_resolve_conditional_distance_or_repetition_choices(self):
        for text in (
            "5-6 miles if injured skip",
            "4-6x800m at 3:00 (1 min rest)",
            "5-6 miles or cross train",
        ):
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), coaching_policy="cj").prescription
                ).unresolved
            )

    def test_range_annotations_do_not_hide_unknown_or_incompatible_steps(self):
        for text in (
            "unknown workout [distance note: 5-6 miles]",
            "Run 20 min [distance note: 5-6 miles]",
            "Run 6 miles [recovery note: 2-3 min rest]",
            "Run 6 miles [distance note: choose whatever]",
            "Run 6 miles [DISTANCE NOTE: 5-6 miles] [distance note: 5-6 miles]",
        ):
            self.assertTrue(parse(text).unresolved)

    def test_range_notes_survive_other_supported_recovery_shapes(self):
        for text, expected, note in (
            ("3x200m smooth (50-60s rest)", 60, "50-60s rest"),
            ("4x45s fast (1-2 min rest)", 120, "1-2 min rest"),
            ("Rest 2-3 min", 180, "2-3 min rest"),
            ("2x (3x500m at 1:45-1:48 w/ 60s rest) 2-3 min rest between sets", 180, "2-3 min rest"),
        ):
            event = normalize_workout(self.event(text), coaching_policy="cj")
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved, text)
            steps = [
                child
                for item in draft.steps
                for child in (item.steps if hasattr(item, "steps") else (item,))
            ]
            matches = [step for step in steps if step.note == note]
            self.assertTrue(matches, text)
            self.assertTrue(all(step.duration == expected for step in matches))
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_approximate_track_time_uses_the_same_approved_pace_tolerance(self):
        text = "4x1000m at ~ 4:00 (1:30 rest)"
        self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)
        event = normalize_workout(self.event(text), coaching_policy="cj")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        work = draft.steps[0].steps[0]
        self.assertEqual(work.duration, 1000)
        self.assertAlmostEqual(work.speed_min, 1609.344 / 391)
        self.assertAlmostEqual(work.speed_max, 1609.344 / 381)
        self.assertIn(text, event.description)
        for profile in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(profile, event))
