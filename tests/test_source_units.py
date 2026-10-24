import unittest

from workoutbridge.calendar import Event
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class SourceUnitTests(unittest.TestCase):
    def event(self, text, description=""):
        return Event("synthetic", "unit", "", "2030-01-01", "Run: " + text, description)

    def test_bare_distance_uses_explicit_source_preference(self):
        for unit, factor in (("km", 1000), ("mi", 1609.344)):
            event = normalize_workout(self.event("12 easy"), distance_unit=unit)
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[0].duration, 12 * factor)
            self.assertEqual(draft.steps[0].display_unit, unit)
            self.assertIn("Unspecified distances", event.description)
            self.assertIn("12 easy", event.description)

    def test_missing_unit_context_requires_review_and_explicit_units_win(self):
        self.assertTrue(parse(normalize_workout(self.event("12 easy")).prescription).unresolved)
        event = normalize_workout(self.event("12 miles easy"), distance_unit="km")
        self.assertEqual(parse(event.prescription).steps[0].duration, 12 * 1609.344)
        for text in ("12 easy if pain stops", "10-12 easy", "3x1200"):
            self.assertTrue(
                parse(
                    normalize_workout(
                        self.event(text), distance_unit="km", coaching_policy="strict"
                    ).prescription
                ).unresolved
            )
        with self.assertRaises(ValueError):
            normalize_workout(self.event("12 easy"), distance_unit="meters")

    def test_feed_metadata_and_cj_rep_units_are_independent(self):
        event = self.event("12 easy", "Workout: Run\nPlanned: 12 km\n")
        draft = parse(normalize_workout(event).prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].duration, 12000)
        event = normalize_workout(
            self.event("12 easy + 3x1200 + 3x (1 hard; 1 easy)"),
            distance_unit="km",
            coaching_policy="cj",
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].duration, 12000)
        self.assertEqual(draft.steps[2].steps[0].duration, 1200)
        self.assertEqual(draft.steps[3].steps[0].duration, 60)

    def test_source_units_supply_pace_context_but_never_override_a_written_unit(self):
        event = normalize_workout(
            self.event("4x800m at 4:10-4:20 pace (1:20 rest)"), distance_unit="km"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertAlmostEqual(draft.steps[0].steps[0].speed_min, 1000 / 260)
        event = normalize_workout(
            self.event("4x800m at 6:30-6:40/mi (1:20 rest)"), distance_unit="km"
        )
        self.assertAlmostEqual(
            parse(event.prescription).steps[0].steps[0].speed_min, 1609.344 / 400
        )
