import unittest

from workoutbridge.calendar import Event
from workoutbridge.parser import Repeat, Step, parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class StridesTests(unittest.TestCase):
    def test_lap_strides_for_both_sources(self):
        for normalize, title in (
            (normalize_workout, "4 strides"),
            (normalize_workout, "Run 3 miles + 4 strides"),
            (normalize_finalsurge, "Run: 3 miles + 4 strides"),
        ):
            with self.subTest(title=title):
                event = Event("synthetic", "strides", "", "2030-01-01", title, "")
                draft = parse(normalize(event).prescription)
                self.assertFalse(draft.unresolved)
                self.assertEqual(
                    draft.steps[-1],
                    Repeat(
                        4,
                        (
                            Step("run", None, "lap_button", note="stride"),
                            Step("rest", None, "lap_button"),
                        ),
                        skip_last_recovery=False,
                    ),
                )

    def test_review_opt_out_and_unknown_instructions(self):
        for title in ("4 strides", "4 strides with 30 sec recovery", "0 strides", "101 strides"):
            event = Event("synthetic", "strides", "", "2030-01-01", title, "")
            self.assertTrue(
                parse(normalize_workout(event, recovery_choice="review").prescription).unresolved
            )
        for title in ("0 strides", "101 strides", "4 strides with 30 sec recovery"):
            event = Event("synthetic", "strides", "", "2030-01-01", title, "")
            self.assertTrue(parse(normalize_workout(event).prescription).unresolved)

    def test_description_rep_count_takes_precedence(self):
        for normalize, title in (
            (normalize_workout, "4 strides"),
            (normalize_finalsurge, "Run: 4 strides"),
        ):
            event = Event("synthetic", "strides", "", "2030-01-01", title, "5 strides")
            normalized = normalize(event)
            draft = parse(normalized.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[-1].count, 5)
            self.assertIn(title, normalized.description)
