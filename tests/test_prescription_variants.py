"""Synthetic coaching dialect examples; never copied athlete records."""

import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Step, parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class PrescriptionVariantTests(unittest.TestCase):
    def event(self, title, description=""):
        return Event("synthetic", "dialect", "", "2030-05-02", title, description)

    def draft(self, title, description="", **options):
        return parse(normalize_workout(self.event(title, description), **options).prescription)

    def test_terminal_periods_and_singular_units_preserve_full_instructions(self):
        for text in ("Run: 8.5 Miles easy.", "Run: 1 mile easy", "Run: 35 minutes easy."):
            self.assertFalse(self.draft(text).unresolved, text)
        for text in ("Run: 8 miles easy. Add another set", "Run: 8 miles easy... coach to clarify"):
            self.assertTrue(self.draft(text).unresolved)

    def test_directional_strides_and_shared_noun_keep_terrain_and_final_recovery(self):
        for text in (
            "Run: 8 miles + 2x uphill strides + 3x downhill strides",
            "Run: 8 miles + 2x uphill + 3x downhill strides",
        ):
            draft = self.draft(text)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[1], Step("run", None, "lap_button"))
            for group, count, direction in zip(draft.steps[2:], (2, 3), ("uphill", "downhill")):
                self.assertEqual(group.count, count)
                self.assertIn(direction, group.steps[0].note.lower())
                self.assertEqual(group.steps[0].unit, "lap_button")
                self.assertEqual(group.steps[1].unit, "lap_button")
                self.assertFalse(group.skip_last_recovery)

    def test_timed_hill_sprints_and_strides_preserve_count_and_duration(self):
        for activity, final_recovery in (
            ("Hill Sprints", True),
            ("strides", False),
            ("hill strides", False),
        ):
            draft = self.draft("Run: 8 miles + 3x14s " + activity)
            self.assertFalse(draft.unresolved)
            group = draft.steps[-1]
            self.assertEqual(group.count, 3)
            self.assertEqual(group.steps[0].duration, 14)
            self.assertIn(activity.split()[-1].rstrip("s").lower(), group.steps[0].note.lower())
            self.assertEqual(group.skip_last_recovery, not final_recovery)

    def test_timed_effort_and_distance_strides_use_documented_implied_lap_policy(self):
        for title, duration, unit in (
            ("Run: 8 miles + 5x25s smooth", 25, "seconds"),
            ("Run: 8 miles + 3x120m strides", 120, "meters"),
        ):
            draft = self.draft(title)
            self.assertFalse(draft.unresolved)
            group = draft.steps[-1]
            self.assertEqual(group.steps[0].duration, duration)
            self.assertEqual(group.steps[0].unit, unit)
            self.assertEqual(group.steps[1].unit, "lap_button")
            self.assertTrue(group.skip_last_recovery)
            self.assertTrue(self.draft(title, recovery_choice="review").unresolved)

    def test_explicit_distance_recovery_keeps_prescribed_time_and_effort(self):
        event = normalize_workout(
            self.event("Run: 8 miles + 3x250m Smooth (~1:40 rest)"), recovery_choice="review"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[-1]
        self.assertEqual(group.count, 3)
        self.assertEqual(group.steps[0].duration, 250)
        self.assertEqual(group.steps[0].label, "smooth")
        self.assertEqual(group.steps[1], Step("rest", 100, "seconds", "rest"))
        self.assertIn("~1:40 rest", event.description)
        self.assertNotIn("error", review_item("123", event))
        self.assertNotIn("error", review_item("coros:us:synthetic", event))

    def test_fartlek_minutes_clock_recovery_and_multiline_bookends(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            event = self.event(
                "Run: Fartlek", "Warm up 1 mile\n5x (3 min hard; 1:30 easy)\nCool down 1.5 miles"
            )
            draft = parse(normalize(event).prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(
                [s.kind for s in (draft.steps[0], draft.steps[-1])], ["warm_up", "cool_down"]
            )
            group = draft.steps[1]
            self.assertEqual(group.count, 5)
            self.assertEqual([s.duration for s in group.steps], [180, 90])
            self.assertFalse(group.skip_last_recovery)

    def test_multiple_explicit_fartlek_phases_remain_one_native_cycle(self):
        event = normalize_workout(
            self.event("Run: 8 miles + 4x (2 min hard; 1 min easy; 20s fast; 40s moderate)")
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[-1]
        self.assertEqual(group.count, 4)
        self.assertEqual([s.duration for s in group.steps], [120, 60, 20, 40])
        self.assertEqual([s.label for s in group.steps], ["hard", "easy", "fast", "moderate"])
        self.assertFalse(group.skip_last_recovery)
        self.assertNotIn("error", review_item("123", event))
        self.assertNotIn("error", review_item("coros:us:synthetic", event))

    def test_effort_qualifiers_and_fast_finish_do_not_invent_numeric_targets(self):
        for effort in ("easy/mod", "easy/moderate", "steady", "tempo", "fast"):
            draft = self.draft("Run: 8 miles " + effort)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[0].label, effort)
            self.assertIsNone(draft.steps[0].speed_min)
        draft = self.draft("Run - Long Run: 19 miles w/ last 4 miles hard")
        self.assertFalse(draft.unresolved)
        self.assertEqual([s.duration for s in draft.steps], [15 * 1609.344, 4 * 1609.344])
        self.assertEqual(draft.steps[-1].note, "last 4 miles hard")

    def test_unknown_targets_choices_missing_units_and_partial_descriptions_stay_blocked(self):
        for text in (
            "Run: 8 miles + 5x12 Hill sprints",
            "Run: 8 miles + 3x120m strides at 160 bpm",
            "Run: 8 miles + 5x25s smooth with jog down recovery",
            "Run: 8 miles + 4x (1 hard; 1 easy)",
            "Run: 8 miles + 0x14s hill sprints",
            "Run: 8 miles + 101x14s hill sprints",
            "Run: 8 miles + 3x0s hill sprints",
            "Run: 8 miles + 3x3601s hill sprints",
            "Run: 8 miles + 4x (2 min hard; choose recovery)",
        ):
            self.assertTrue(self.draft(text).unresolved, text)
        self.assertTrue(self.draft("Run: 5x250m", "Warm up 1 mile").unresolved)

    def test_generic_repeat_grammar_rejects_nested_empty_or_excessive_cycles(self):
        for text in (
            "0 x [Run 30 sec hard | Run 60 sec easy]",
            "101 x [Run 30 sec hard | Run 60 sec easy]",
            "4 x [Run 30 sec hard | ]",
            "4 x [2 x [Run 30 sec hard | Run 60 sec easy] | Run 30 sec]",
        ):
            self.assertTrue(parse(text).unresolved)

    def test_explicit_distance_cycles_preserve_both_phases_and_final_recovery(self):
        for text in (
            "Run: 8 miles + 4x (~180m hard; ~180m moderate)",
            "Run: 8 miles + 4x (1 mile hard; 2 miles moderate)",
        ):
            draft = self.draft(text)
            self.assertFalse(draft.unresolved)
            group = draft.steps[-1]
            self.assertEqual(group.count, 4)
            self.assertEqual([s.unit for s in group.steps], ["meters", "meters"])
            self.assertFalse(group.skip_last_recovery)

    def test_qualitative_effort_notes_do_not_become_invented_numeric_paces(self):
        draft = self.draft(
            "Run: 8 miles + 3x (2 min @ ~ tempo effort; 1 min moderate @ ~ Long Run pace)"
        )
        self.assertFalse(draft.unresolved)
        group = draft.steps[-1]
        self.assertIn("tempo", group.steps[0].label)
        self.assertIn("long run pace", group.steps[1].label)
        self.assertTrue(all(s.speed_min is None for s in group.steps))
        for text in (
            "Run: 8 miles + 3x (2 min hard at 160 bpm; 1 min easy)",
            "Run: 8 miles + 3x (2 min hard if pain stop; 1 min easy)",
            "Run: 3x (1 mile at ~ 6:30 pace; 1 mile moderate)",
            "Run: 3x (1 mile @ ~ 6:30 pace; 1 mile moderate)",
        ):
            self.assertTrue(self.draft(text).unresolved)

    def test_explicit_rest_phase_is_retained_after_every_cycle(self):
        draft = self.draft("Run: 8 miles + 3x (2 min hard; 90s rest)")
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[-1].steps[-1].kind, "rest")
        self.assertEqual(draft.steps[-1].steps[-1].duration, 90)
        self.assertFalse(draft.steps[-1].skip_last_recovery)

    def test_common_bookend_spellings_do_not_hide_a_missing_main_workout(self):
        draft = self.draft(
            "Run: Fartlek", "Warmup 1 mile\n3x (2 min hard; 1 min easy)\nCool Donw 1 mile"
        )
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].kind, "warm_up")
        self.assertEqual(draft.steps[-1].kind, "cool_down")
        self.assertTrue(self.draft("Run: 5x250m", "WU 1 mile").unresolved)

    def test_fractional_mile_phases_are_explicit_distances(self):
        for fraction in ("1/2", "½"):
            draft = self.draft(f"Run: 8 miles + 3x (2 min hard; 1 min easy) + {fraction} mile easy")
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[-1].duration, 804.672)
        self.assertTrue(self.draft("Run: 3x (1/2 hard; 1 min easy)").unresolved)

    def test_jog_and_very_hard_phases_keep_their_qualitative_labels(self):
        draft = self.draft("Run: 8 miles + 3x (40s very hard; 80s jog)")
        self.assertFalse(draft.unresolved)
        self.assertEqual([s.label for s in draft.steps[-1].steps], ["very hard", "jog"])
        self.assertFalse(draft.steps[-1].skip_last_recovery)

    def test_stride_effort_modifiers_are_preserved(self):
        for label in ("hard strides", "smooth strides", "fast strides"):
            draft = self.draft("Run: 8 miles + 3x120m " + label)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[-1].steps[0].label, label)
