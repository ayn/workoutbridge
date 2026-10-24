import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class CJConditionTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "condition", "", "2030-03-01", "Run: " + text, "")

    def test_nominal_run_keeps_condition_on_its_step_only_when_enabled(self):
        for text, distance, condition in (
            ("5-6 miles if feeling okay", 6 * 1609.344, "if feeling okay"),
            ("7 miles if weather allows", 7 * 1609.344, "if weather allows"),
            (
                "7 miles if feeling okay, but stop if needed",
                7 * 1609.344,
                "if feeling okay, but stop if needed",
            ),
        ):
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), coaching_policy="strict").prescription
                ).unresolved
            )
            event = normalize_workout(self.event(text), coaching_policy="cj")
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[0].duration, distance)
            self.assertIn(condition, draft.steps[0].note)
            if "5-6" in text:
                self.assertIn("5-6 miles", draft.steps[0].note)
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_conditional_bare_distance_uses_source_units(self):
        event = normalize_workout(
            self.event("12 easy if feeling okay"), coaching_policy="cj", distance_unit="km"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].duration, 12000)
        self.assertEqual(draft.steps[0].note, "if feeling okay")

    def test_alternatives_and_conditional_sets_still_need_review(self):
        for text in (
            "6 miles or cross train",
            "6 miles or bike if sore",
            "4x800m if feeling okay",
            "5-6 miles if feeling okay; add unspecified intervals",
            "6 miles if feeling okay. Then do 4 strides",
        ):
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), coaching_policy="cj").prescription
                ).unresolved
            )

    def test_optional_easy_double_stays_a_note_on_the_single_nominal_run(self):
        for note in ("Optional easy double", "Optional easy double or x-train"):
            event = normalize_workout(self.event("9-11 miles easy. " + note), coaching_policy="cj")
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(len(draft.steps), 1)
            self.assertEqual(draft.steps[0].duration, 11 * 1609.344)
            self.assertIn(note, draft.steps[0].note)
        self.assertTrue(
            parse(
                normalize_workout(
                    self.event("9-11 miles easy. Optional easy double. Also do mandatory strides"),
                    coaching_policy="cj",
                ).prescription
            ).unresolved
        )
