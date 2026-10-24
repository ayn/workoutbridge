import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class CoachingTargetTests(unittest.TestCase):
    def convert(self, description, title="Synthetic workout", metadata=True):
        if metadata:
            title = "Run: " + title
            description = "Workout: Run\nPlanned: 9 mi\n\n" + description
        return normalize_workout(
            Event("synthetic", "target-workout", "", "2031-02-02", title, description)
        )

    def test_track_rep_times_are_not_misread_as_per_mile_paces(self):
        event = self.convert(
            "Warm up 1.2 miles\n4x800m at ~ 2:55-3:00 (1:20 rest)\nCool down 1.2 miles"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[1]
        self.assertEqual(group.count, 4)
        self.assertEqual(group.steps[0].duration, 800)
        self.assertAlmostEqual(group.steps[0].speed_min, 800 / 180)
        self.assertAlmostEqual(group.steps[0].speed_max, 800 / 175)
        self.assertEqual(group.steps[1].duration, 80)

    def test_mile_interval_paces_use_the_pace_unit_not_total_rep_distance(self):
        event = self.convert("3x1.25 miles at ~ 6:30-6:40 pace (2:15 rest)")
        group = parse(event.prescription).steps[0]
        self.assertEqual(group.steps[0].duration, 1.25 * 1609.344)
        self.assertAlmostEqual(group.steps[0].speed_min, 1609.344 / 400)
        self.assertAlmostEqual(group.steps[0].speed_max, 1609.344 / 390)
        self.assertEqual(group.steps[1].duration, 135)
        self.assertNotIn("error", review_item("123", event))
        self.assertNotIn("error", review_item("coros:us:synthetic", event))

    def test_explicit_pace_unit_overrides_source_units_and_ambiguous_units_stay_blocked(self):
        event = self.convert("3x1.25 miles at 4:00-4:10/km (2:15 rest)")
        group = parse(event.prescription).steps[0]
        self.assertAlmostEqual(group.steps[0].speed_min, 1000 / 250)
        self.assertAlmostEqual(group.steps[0].speed_max, 1000 / 240)
        unknown = self.convert("4x800m at 3:00-3:10 pace (1:20 rest)", metadata=False)
        self.assertTrue(parse(unknown.prescription).unresolved)

    def test_tempo_pace_band_and_explicit_post_tempo_rest(self):
        event = self.convert("4 miles tempo at ~ 6:35-6:45 pace (6 mins rest)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)
        work, rest = draft.steps
        self.assertEqual(work.label, "tempo")
        self.assertAlmostEqual(work.speed_min, 1609.344 / 405)
        self.assertAlmostEqual(work.speed_max, 1609.344 / 395)
        self.assertEqual(rest.kind, "rest")
        self.assertEqual(rest.duration, 360)

    def test_kilometer_alias_and_unordered_hyphen_bounds(self):
        event = self.convert("5x1k at ~ 4:05-4:00 (1:30 rest)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        run = draft.steps[0].steps[0]
        self.assertEqual(run.duration, 1000)
        self.assertEqual(run.display_unit, "km")
        self.assertAlmostEqual(run.speed_min, 1000 / 245)
        self.assertAlmostEqual(run.speed_max, 1000 / 240)

    def test_abbreviated_clock_range_keeps_the_minutes(self):
        for text in ("3 miles tempo at 6:35-45 pace", "4x800m at 2:50-55 (1:20 rest)"):
            event = self.convert(text)
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            work = draft.steps[0] if "tempo" in text else draft.steps[0].steps[0]
            if "tempo" in text:
                self.assertAlmostEqual(work.speed_min, 1609.344 / 405)
                self.assertAlmostEqual(work.speed_max, 1609.344 / 395)
            else:
                self.assertAlmostEqual(work.speed_min, 800 / 175)
                self.assertAlmostEqual(work.speed_max, 800 / 170)
            self.assertNotIn("error", review_item("coros:us:synthetic", event))
        self.assertTrue(
            parse(self.convert("3 miles tempo at 6:55-05 pace").prescription).unresolved
        )

    def test_explicit_after_set_rest_replaces_the_omitted_final_interval_rest(self):
        event = self.convert("5x1000m at 3:50-3:55 (1:30 rest) (4:00 rest after set)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)
        self.assertTrue(draft.steps[0].skip_last_recovery)
        self.assertEqual(draft.steps[1].kind, "rest")
        self.assertEqual(draft.steps[1].duration, 240)

    def test_invented_tolerance_missing_units_and_progression_arrows_require_policy(self):
        for text in (
            "4x800 at ~ 2:50-2:55 (1:20 rest)",
            "5 miles tempo at ~ 6:30 pace",
            "4x1 mile at 6:30 > 6:15 pace (2:00 rest)",
            "4x800m at 3:00-3:10 (1:20 rest) if knee hurts skip half",
            "4x800m at 3:00-3:10 (1:20 rest) (160 bpm target)",
            "3x2 miles at 6:30-6:40 (2:00 rest)",
        ):
            self.assertTrue(parse(self.convert(text).prescription).unresolved, text)

    def test_canonical_pace_steps_compile_without_losing_native_targets(self):
        draft = parse(
            "Run 4 miles tempo at 6:35-6:45/mi; 3 x 1.25 mi at 6:30-6:40/mi with 135 sec rest recovery"
        )
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].label, "tempo")
        self.assertAlmostEqual(draft.steps[1].steps[0].speed_min, 1609.344 / 400)

    def test_singular_unit_only_rep_means_one_of_the_stated_unit(self):
        event = self.convert("4x mile at 6:45-6:55 (2:00 rest)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].count, 4)
        self.assertEqual(draft.steps[0].steps[0].duration, 1609.344)

    def test_an_explicit_rest_or_lap_transition_does_not_get_an_extra_buffer(self):
        event = self.convert(
            "4 miles tempo at 6:35-6:45 pace (6 mins rest)\n3x200m at 42-44 (1:30 rest)"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 3)
        self.assertEqual(draft.steps[1].kind, "rest")
        event = self.convert("Run until lap + 3x120m strides")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)

    def test_continuous_paced_run_phases_do_not_gain_interval_transition(self):
        event = self.convert("2 miles easy\n3 miles tempo at 6:35-6:45 pace")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)
        self.assertTrue(all(step.unit == "meters" for step in draft.steps))
