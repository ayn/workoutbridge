import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class CoachingSetTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "sets", "", "2030-02-01", "Run: Intervals", text)

    def test_repeated_track_sets_keep_reps_and_between_set_rest(self):
        for text in (
            "2x (3x500m at 1:45-1:48 w/ 60s rest) 3:00 rest between sets",
            "2x (3x500m at 1:45-1:48 w/ 60s rest)\n3:00 rest in-between sets",
        ):
            event = normalize_workout(self.event(text))
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(len(draft.steps), 3)
            first, rest, second = draft.steps
            self.assertEqual(first, second)
            self.assertEqual(first.count, 3)
            self.assertEqual(first.steps[0].duration, 500)
            self.assertEqual(first.steps[1].duration, 60)
            self.assertTrue(first.skip_last_recovery)
            self.assertEqual(rest.duration, 180)
            self.assertEqual(rest.kind, "rest")
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_nested_sets_reject_missing_or_variable_rest_and_excessive_expansion(self):
        for text in (
            "2x (3x500m at 1:45-1:48 w/ 60s rest)",
            "2x (3x500m at 1:45-1:48 w/ 60s rest) 2-3 min rest between sets",
            "100x (100x500m at 1:45-1:48 w/ 60s rest) 3:00 rest between sets",
            "2x (3x500m at 1:45-1:48 w/ 60s rest) 3:00 rest between sets if injured stop",
        ):
            self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)

    def test_timed_hills_keep_direction_and_recovery_movement_until_lap(self):
        for text, direction, recovery in (
            ("5x35s uphill (jog down)", "uphill", "jog down"),
            ("5x35s downhill (jog up)", "downhill", "jog up"),
            ("5x35s hills (walk down)", "hills", "walk down"),
            ("5x35s strides uphill", "uphill strides", ""),
        ):
            event = normalize_workout(self.event(text))
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved, text)
            group = draft.steps[0]
            self.assertEqual(group.count, 5)
            self.assertEqual(group.steps[0].duration, 35)
            self.assertIn(direction, group.steps[0].note.lower())
            self.assertEqual(group.steps[1].unit, "lap_button")
            self.assertEqual(group.steps[1].note, recovery)
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), recovery_choice="review").prescription
                ).unresolved
            )
            for profile in ("123", "coros:us:synthetic"):
                self.assertNotIn("error", review_item(profile, event))

    def test_timed_reps_preserve_explicit_rest_and_omit_final_rest_before_cooldown(self):
        event = normalize_workout(self.event("4x45s fast (1:20 rest)\nCool down 1 mile"))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[0]
        self.assertEqual(group.count, 4)
        self.assertEqual(group.steps[0].duration, 45)
        self.assertEqual(group.steps[0].label, "fast")
        self.assertEqual(group.steps[1].duration, 80)
        self.assertTrue(group.skip_last_recovery)

    def test_clock_recovery_suffix_and_standalone_rest_are_preserved(self):
        event = normalize_workout(
            self.event("3x200m smooth (~1:20 min rest)\nRest 3:00 mins\n4x45s fast (1:20 rest)")
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].steps[1].duration, 80)
        self.assertEqual(draft.steps[1].kind, "rest")
        self.assertEqual(draft.steps[1].duration, 180)

    def test_tempo_effort_with_explicit_easy_phase_is_continuous(self):
        event = normalize_workout(self.event("12 min tempo effort (4 mins easy)"))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual([step.duration for step in draft.steps], [720, 240])
        self.assertEqual([step.label for step in draft.steps], ["tempo effort", "easy"])

    def test_named_effort_relationships_remain_notes_without_numeric_targets(self):
        for policy in ("strict", "cj"):
            event = normalize_workout(
                self.event(
                    "3x (4 min hard at 10k effort; 2 min moderate around regular run pace; 1 min fast around 5k pace or faster; 2 min easy)"
                ),
                coaching_policy=policy,
            )
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual([s.duration for s in draft.steps[0].steps], [240, 120, 60, 120])
            self.assertTrue(all(s.speed_min is None for s in draft.steps[0].steps))
            event = normalize_workout(
                self.event("3x (6 min at 1/2 marathon race pace effort; 3 min moderate)"),
                coaching_policy=policy,
            )
            draft = parse(event.prescription)
            self.assertFalse(draft.unresolved)
            self.assertIn("1/2 marathon", draft.steps[0].steps[0].label)

    def test_fast_finish_singular_units_and_qualitative_progression_keep_the_split(self):
        for finish in ("3 mile fast", "3 miles progressively faster"):
            event = Event(
                "synthetic", "finish", "", "2030-02-01", "Run: 14 miles w/ last " + finish, ""
            )
            draft = parse(normalize_workout(event).prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual([s.duration for s in draft.steps], [11 * 1609.344, 3 * 1609.344])
            self.assertIn(finish.split(" ", 2)[2], draft.steps[-1].note)
