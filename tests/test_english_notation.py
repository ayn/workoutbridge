import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class EnglishNotationTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "english", "", "2030-03-01", text, "")

    def test_plus_and_singular_second_are_shared_grammar(self):
        event = normalize_workout(self.event("8 miles easy plus 3 x 18 second hills"))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].duration, 8 * 1609.344)
        self.assertEqual(draft.steps[-1].steps[0].duration, 18)
        self.assertIn("plus", event.description)

    def test_slash_cycles_with_explicit_units_preserve_all_phases(self):
        for text in (
            "4 x 3 minutes fast/90 seconds easy",
            "4 x (3 minutes fast/90 seconds easy)",
            "4 x (3 minutes fast plus 90 seconds easy)",
        ):
            event = normalize_workout(self.event(text))
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved, text)
            self.assertEqual([s.duration for s in draft.steps[0].steps], [180, 90])
            self.assertFalse(draft.steps[0].skip_last_recovery)
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_commas_separate_complete_workout_clauses(self):
        event = normalize_workout(
            self.event("3 miles easy, 4 x 2 minutes fast/1 minute easy, 2 miles easy")
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].duration, 3 * 1609.344)
        self.assertEqual(draft.steps[-1].duration, 2 * 1609.344)

    def test_slashes_inside_fractional_efforts_and_pace_units_are_not_separators(self):
        for text in (
            "3 x (1 mile at 6:30-6:40/mi / 1 mile at 7:30-7:40/mi)",
            "3 x (4 min at 1/2 marathon race pace effort/2 min easy)",
        ):
            draft = parse(normalize_workout(self.event(text)).prescription)
            self.assertFalse(draft.unresolved, text)
            self.assertEqual(len(draft.steps[0].steps), 2)
        for text in (
            "8 miles easy plus choose extra workout",
            "4 x 3 minutes fast/unknown recovery",
            "8 miles easy, keep heart rate below 140",
        ):
            self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)
