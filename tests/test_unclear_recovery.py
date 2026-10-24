import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class UnclearRecoveryTests(unittest.TestCase):
    def event(self, text, **options):
        return normalize_workout(
            Event(
                "synthetic", "unclear-recovery", "", "2030-01-01", "Run: Synthetic workout", text
            ),
            **options,
        )

    def draft(self, text, **options):
        event = self.event(text, **options)
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved, text)
        for profile in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(profile, event))
        return draft

    def test_unspecified_recovery_on_paced_reps_is_lap_not_an_invented_time(self):
        for text in (
            "4x800m at 3:05-3:10",
            "4x800m at 3:05-3:10 (choose recovery)",
            "4x800m at 3:05-3:10 (full recovery)",
        ):
            draft = self.draft(text)
            group = draft.steps[0]
            self.assertIsInstance(group, Repeat)
            self.assertEqual(
                (group.steps[-1].kind, group.steps[-1].unit, group.steps[-1].duration),
                ("rest", "lap_button", None),
            )
            self.assertAlmostEqual(group.steps[0].speed_min, 800 / 190)
            self.assertTrue(group.skip_last_recovery)
            for options in ({"coaching_policy": "strict"}, {"recovery_choice": "review"}):
                self.assertTrue(parse(self.event(text, **options).prescription).unresolved)

    def test_missing_recovery_duration_inside_cycle_and_standalone_rest(self):
        for phrase in ("moderate", "recover until ready", "recovery as needed"):
            draft = self.draft("5x (90 sec hard; " + phrase + ")")
            self.assertFalse(draft.steps[0].skip_last_recovery)
            last = draft.steps[0].steps[-1]
            self.assertEqual((last.kind, last.unit), ("rest", "lap_button"))
            self.assertIn(phrase, last.note)
        for phrase in ("full recovery", "rest as needed", "choose recovery"):
            draft = self.draft("Run 2 miles; " + phrase + "; Run 1 mile easy")
            self.assertEqual(draft.steps[1].unit, "lap_button")
            self.assertIn(phrase, draft.steps[1].note)

    def test_explicit_times_and_distance_recoveries_stay_prescribed(self):
        draft = self.draft("5x (90 sec hard; 1:15)")
        self.assertEqual(
            (draft.steps[0].steps[-1].kind, draft.steps[0].steps[-1].duration), ("rest", 75)
        )
        draft = self.draft("4x800m at 3:05-3:10 (90 sec rest)")
        self.assertEqual(draft.steps[0].steps[-1].duration, 90)
        draft = self.draft("4x800m at 3:05-3:10 w/ 200m jog in 75-90s")
        self.assertEqual(draft.steps[0].steps[-1].duration, 200)
        self.assertEqual(draft.steps[0].steps[-1].unit, "meters")

    def test_unclear_after_set_rest_is_lap_and_preserves_between_rep_time(self):
        draft = self.draft("4x800m at 3:05-3:10 (90 sec rest) (full rest after set)")
        self.assertEqual(draft.steps[0].steps[-1].duration, 90)
        self.assertEqual((draft.steps[1].kind, draft.steps[1].unit), ("rest", "lap_button"))
        self.assertIn("full rest", draft.steps[1].note)

    def test_single_paced_work_keeps_its_explicit_target_before_unclear_rest(self):
        draft = self.draft("3 miles at 6:30-6:40/mi (full recovery)")
        self.assertEqual(draft.steps[0].duration, 3 * 1609.344)
        self.assertAlmostEqual(draft.steps[0].speed_min, 1609.344 / 400)
        self.assertEqual(draft.steps[1].unit, "lap_button")
        self.assertTrue(parse("Run 3 miles [buffer note: full recovery]").unresolved)

    def test_timed_reps_support_explicitly_unclear_recovery(self):
        draft = self.draft("4x45s fast (full recovery)")
        self.assertEqual(draft.steps[0].steps[-1].unit, "lap_button")
        self.assertIn("full recovery", draft.steps[0].steps[-1].note)

    def test_explicit_minute_units_are_supported_with_lap_recovery(self):
        for text, duration in (
            ("4 x 1 min uphill with lap recovery jog down", 60),
            ("4 x 0.5 minutes hills with lap recovery", 30),
            ("4 x 0.25 min strides with lap recovery", 15),
            ("4 x 0.2 min uphill sprints with lap recovery", 12),
            ("4 x 1 min hard with lap recovery", 60),
        ):
            draft = parse(text)
            self.assertFalse(draft.unresolved, text)
            self.assertEqual(draft.steps[0].steps[0].duration, duration)
        for text in ("4 x 0 min uphill with lap recovery", "4 x 2 hours uphill with lap recovery"):
            self.assertTrue(parse(text).unresolved)

    def test_unknown_work_and_alternatives_are_not_misread_as_recovery(self):
        for text in (
            "5x (hard; full recovery)",
            "4x800m at 3:05-3:10 (rest and add 4 sprints)",
            "4x800m at 3:05-3:10 (90 sec rest or 200m jog)",
            "5x (90 sec hard; choose another workout)",
            "recover for 200 watts",
            "Run 4 miles or cross train",
        ):
            self.assertTrue(parse(self.event(text).prescription).unresolved, text)
