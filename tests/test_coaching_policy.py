import unittest

from workoutbridge.calendar import Event
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class CoachingPolicyTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "policy", "", "2030-01-01", "Run: " + text, "")

    def test_unitless_cj_shorthand_is_explicit_opt_in(self):
        for text, duration, unit in (
            ("3x1200", 1200, "meters"),
            ("3x12 hill sprints", 12, "seconds"),
            ("3x (1 hard; 1 easy)", 60, "seconds"),
            ("3x (1 hard/1 easy)", 60, "seconds"),
        ):
            event = self.event(text)
            self.assertTrue(parse(normalize_workout(event).prescription).unresolved)
            normalized = normalize_workout(event, coaching_policy="cj")
            draft = parse(normalized.prescription)
            self.assertFalse(draft.unresolved, text)
            self.assertEqual(draft.steps[0].steps[0].duration, duration)
            self.assertEqual(draft.steps[0].steps[0].unit, unit)
            self.assertIn("CJ policy", normalized.description)
            self.assertIn(text, normalized.description)

    def test_pace_progression_band_preserves_direction_in_notes(self):
        text = "4x1 mile at 6:25 -> 6:10 pace (2:00 rest)"
        event = self.event(text)
        self.assertTrue(parse(normalize_workout(event).prescription).unresolved)
        normalized = normalize_workout(event, coaching_policy="cj")
        draft = parse(normalized.prescription)
        self.assertFalse(draft.unresolved)
        work = draft.steps[0].steps[0]
        self.assertAlmostEqual(work.speed_min, 1609.344 / 385)
        self.assertAlmostEqual(work.speed_max, 1609.344 / 370)
        self.assertIn("progression", work.note)
        self.assertIn(text, normalized.description)

    def test_approximate_pace_tolerance_is_five_seconds_per_mile(self):
        event = self.event("4 miles tempo at ~ 6:40/mi")
        self.assertTrue(parse(normalize_workout(event).prescription).unresolved)
        draft = parse(normalize_workout(event, coaching_policy="cj").prescription)
        self.assertFalse(draft.unresolved)
        self.assertAlmostEqual(draft.steps[0].speed_min, 1609.344 / 405)
        self.assertAlmostEqual(draft.steps[0].speed_max, 1609.344 / 395)

    def test_cj_policy_does_not_resolve_choices_or_unknown_instructions(self):
        for text in (
            "3x1200 or 4x800",
            "3x12 hill sprints if injured skip",
            "3x (1 hard; choose recovery)",
            "3x1200 at 4:00 (choose recovery)",
        ):
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), coaching_policy="cj").prescription
                ).unresolved
            )
        with self.assertRaises(ValueError):
            normalize_workout(self.event("3x1200"), coaching_policy="unknown")
