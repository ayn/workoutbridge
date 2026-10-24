import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class CoachingProseTests(unittest.TestCase):
    def normalize(self, text, **options):
        return normalize_workout(
            Event("synthetic", "coaching-prose", "", "2030-02-01", "Run: Synthetic workout", text),
            **options,
        )

    def draft(self, text, **options):
        event = self.normalize(text, **options)
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved, text)
        for profile in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(profile, event))
        return draft

    def test_elapsed_rep_with_matching_parenthetical_pace_and_after_rest(self):
        text = "4x1k at 4:00-4:05 (6:26-6:34 pace) (90s rest) (4:00 rest after 4th)"
        draft = self.draft(text, distance_unit="mi")
        work = draft.steps[0].steps[0]
        self.assertAlmostEqual(work.speed_min, 1609.344 / 394)
        self.assertAlmostEqual(work.speed_max, 1609.344 / 386)
        self.assertTrue(draft.steps[0].skip_last_recovery)
        self.assertEqual(draft.steps[0].steps[-1].duration, 90)
        self.assertEqual(draft.steps[1].duration, 240)
        self.assertTrue(
            parse(
                self.normalize(
                    text.replace("6:26-6:34", "5:00-5:10"), distance_unit="mi"
                ).prescription
            ).unresolved
        )

    def test_second_rest_is_after_set_and_last_one_alias_is_supported(self):
        for suffix in (
            "(4 min rest)",
            "(4 min rest after last one)",
            "(4 min rest after the last rep)",
        ):
            draft = self.draft("4x1k at 4:00-4:05 (90s rest) " + suffix)
            self.assertEqual(
                [x.kind if not isinstance(x, Repeat) else "repeat" for x in draft.steps],
                ["repeat", "rest"],
            )
            self.assertEqual(draft.steps[1].duration, 240)
        self.assertTrue(
            parse(
                self.normalize(
                    "4x1k at 4:00-4:05 (90s rest) (4 min rest) (5 min rest)"
                ).prescription
            ).unresolved
        )

    def test_progressive_starting_at_and_around_keep_direction_in_step_note(self):
        draft = self.draft("4x mile starting at ~7:00 -> 6:40 (2 min rest)")
        self.assertIn("7:00 -> 6:40", draft.steps[0].steps[0].note)
        self.assertEqual(draft.steps[0].steps[-1].duration, 120)
        draft = self.draft("3 miles at around 7:20 pace")
        self.assertAlmostEqual(draft.steps[0].speed_min, 1609.344 / 445)
        self.assertAlmostEqual(draft.steps[0].speed_max, 1609.344 / 435)

    def test_following_run_and_colon_fartlek_preserve_every_phase(self):
        draft = self.draft(
            "3x (2:00 hard; 1:00 moderate); 4x (20s fast; 40s easy); Right into 0.75 mile hard after last 40s easy"
        )
        self.assertFalse(draft.steps[0].skip_last_recovery)
        self.assertFalse(draft.steps[1].skip_last_recovery)
        self.assertEqual(draft.steps[-1].duration, 0.75 * 1609.344)
        self.assertEqual(draft.steps[-1].label, "hard")
        draft = self.draft("5 miles + 4x (1:20 hard: 1:20 easy)")
        self.assertFalse(draft.steps[-1].skip_last_recovery)
        self.assertEqual([s.duration for s in draft.steps[-1].steps], [80, 80])

    def test_effort_qualified_strides_and_bare_k_alias(self):
        draft = self.draft("5 miles + 3 easy strides + 4x150m smooth + 3x80m hard strides")
        self.assertEqual(draft.steps[1].unit, "lap_button")
        self.assertEqual([s.count for s in draft.steps if isinstance(s, Repeat)], [3, 4, 3])
        self.assertIn("easy", draft.steps[2].steps[0].note)
        self.assertFalse(draft.steps[3].skip_last_recovery)
        self.assertFalse(draft.steps[4].skip_last_recovery)
        draft = self.draft("4x1k + 3x150m smooth")
        self.assertEqual(draft.steps[0].steps[0].duration, 1000)

    def test_structured_coaching_notes_attach_to_work_without_hiding_unknown_clauses(self):
        draft = parse(
            "3 x [Run 1 mile at 6:50-7:00/mi [coaching note: Final fast rep quicker] | Run 1 mile at 7:30-7:40/mi]"
        )
        self.assertFalse(draft.unresolved)
        self.assertIn("Final fast rep quicker", draft.steps[0].steps[0].note)
        for text in (
            "Run 3 miles [coaching note: nested [unknown]]",
            "unknown [coaching note: easy]",
            "Run 3 miles; add extra reps",
        ):
            self.assertTrue(parse(text).unresolved)

    def test_qualitative_terrain_and_optional_double_are_notes_for_complete_workouts(self):
        for text in ("7-9 miles very easy", "14 miles easy/mod over hills"):
            draft = self.draft(text)
            self.assertIsNone(draft.steps[0].speed_min)
        event = self.normalize("7 miles easy plus 4 x 25 second hills. Optional easy double")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[-1].count, 4)
        self.assertIn("Optional easy double", draft.steps[-1].steps[0].note)
        self.assertTrue(
            parse(
                self.normalize("7 miles easy plus choose a set. Optional easy double").prescription
            ).unresolved
        )

    def test_unspecified_rest_is_lap_ended_and_does_not_add_an_extra_transition(self):
        for rest in ("Rest", "short rest"):
            draft = self.draft("4 miles easy + " + rest + " + 3 easy strides")
            self.assertEqual(len(draft.steps), 3)
            self.assertEqual((draft.steps[1].kind, draft.steps[1].unit), ("rest", "lap_button"))
            self.assertTrue(
                parse(
                    self.normalize(
                        "4 miles easy + " + rest + " + 3 easy strides", coaching_policy="strict"
                    ).prescription
                ).unresolved
            )

    def test_total_distance_mixed_in_and_fixed_opening_use_lap_finish(self):
        draft = self.draft("11 miles w/ 5x (1 min hard; 1 min easy mixed in)")
        self.assertEqual(draft.steps[0].unit, "lap_button")
        self.assertEqual(draft.steps[-1].unit, "lap_button")
        self.assertIn("11 miles total", draft.steps[-1].note)
        draft = self.draft("12 miles w/ 5x (1 min hard; 1 min easy) after 8 miles")
        self.assertEqual(draft.steps[0].duration, 8 * 1609.344)
        self.assertEqual(draft.steps[-1].unit, "lap_button")
        self.assertIn("12 miles total", draft.steps[-1].note)
        self.assertTrue(
            parse(
                self.normalize(
                    "12 miles w/ 5x (1 min hard; 1 min easy) after 14 miles"
                ).prescription
            ).unresolved
        )

    def test_unknown_recovery_and_malformed_numbers_still_require_review(self):
        for text in (
            "3x (2:00 hard: decide recovery)",
            "4x1k at 4:00-4:05 (90s rest) (4 min rest after 3rd)",
            "Right into 0.75 mile hard after last unknown work",
            "4x1k at ~4;00 (90s rest)",
        ):
            self.assertTrue(
                parse(self.normalize(text, distance_unit="mi").prescription).unresolved, text
            )
