import unittest

from workoutbridge.calendar import Event
from workoutbridge.coros import workout_payload as coros_payload
from workoutbridge.garmin import workout_payload as garmin_payload
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class FinalExplicitRecoveryTests(unittest.TestCase):
    def normalize(self, text, policy="athlete_preferences"):
        return normalize_workout(
            Event("synthetic", "final-recovery", "", "2032-03-04", "Run: Intervals", text),
            coaching_policy=policy,
        )

    def test_consecutive_track_sets_keep_every_prescribed_rest(self):
        event = self.normalize(
            "Warm up 1 mile\n4x600m at 2:10-2:12 (75 sec rest)\n"
            "5x300m at 1:00-1:02 (45 sec rest)\nCool down 1 mile"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        groups = [step for step in draft.steps if isinstance(step, Repeat)]
        self.assertEqual([group.count for group in groups], [4, 5])
        self.assertTrue(all(not group.skip_last_recovery for group in groups))
        sections = coros_payload("Synthetic intervals", "", draft)["sections"]
        self.assertEqual(len(sections), 4)
        self.assertEqual([section["repeats"] for section in sections[1:3]], [4, 5])
        self.assertEqual(
            [section["sets"][-1]["targetValue"] for section in sections[1:3]], [75, 45]
        )
        garmin = garmin_payload("Synthetic intervals", "", draft)["workoutSegments"][0][
            "workoutSteps"
        ]
        self.assertEqual([step["skipLastRestStep"] for step in garmin[1:3]], [False, True])
        self.assertIn("final", event.description.lower())

    def test_garmin_cooldown_omission_is_optional_and_does_not_change_coros(self):
        event = self.normalize("4x600m at 2:10-2:12 (75 sec rest)\nCool down 1 mile")
        draft = parse(event.prescription)
        garmin = garmin_payload("Synthetic", "", draft)["workoutSegments"][0]["workoutSteps"]
        self.assertTrue(garmin[0]["skipLastRestStep"])
        self.assertFalse(draft.steps[0].skip_last_recovery)
        explicit = garmin_payload("Synthetic", "", draft, skip_recovery_before_cooldown=False)
        self.assertFalse(explicit["workoutSegments"][0]["workoutSteps"][0]["skipLastRestStep"])
        coros = coros_payload("Synthetic", "", draft)["sections"]
        self.assertEqual(coros[0]["repeats"], 4)
        self.assertEqual(coros[0]["sets"][-1]["targetValue"], 75)
        self.assertEqual(coros[1]["sectionType"], 4)

    def test_canonical_marker_can_retain_timed_and_distance_rest(self):
        for clause in (
            "4 x 600 m in 130-132 sec with 75 sec rest recovery",
            "4 x 600 m at 5:40-5:50/mi with 75 sec rest recovery",
            "4 x 45 sec hard with 75 sec rest recovery",
            "4 x 600 m in 130-132 sec with 200 m in 75-80 sec recovery",
        ):
            with self.subTest(clause=clause):
                draft = parse(clause + " including final recovery")
                self.assertFalse(draft.unresolved)
                self.assertFalse(draft.steps[0].skip_last_recovery)

    def test_explicit_between_set_rest_replaces_short_final_rest(self):
        event = self.normalize("4x600m at 2:10-2:12 (75 sec rest) (4:00 rest after set)")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertTrue(draft.steps[0].skip_last_recovery)
        self.assertEqual(draft.steps[1].duration, 240)

    def test_separate_between_set_rest_replaces_the_final_short_rest(self):
        event = self.normalize(
            "4x600m at 2:10-2:12 (75 sec rest)\nRest 3 min\n"
            "5x300m at 1:00-1:02 (45 sec rest)\nCool down 1 mile"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        first, rest, second, _ = draft.steps
        self.assertTrue(first.skip_last_recovery)
        self.assertEqual(rest.duration, 180)
        self.assertFalse(second.skip_last_recovery)
        sections = coros_payload("Synthetic sets", "", draft)["sections"]
        self.assertEqual(sections[0]["repeats"], 4)
        self.assertEqual(sections[1]["targetValue"], 105)
        self.assertEqual(sections[2]["repeats"], 5)
        garmin = garmin_payload("Synthetic sets", "", draft)["workoutSegments"][0]["workoutSteps"]
        self.assertTrue(garmin[0]["skipLastRestStep"])
        self.assertEqual(garmin[1]["endConditionValue"], 180)

    def test_strict_policy_and_implied_lap_recovery_keep_their_contract(self):
        for text, policy in (
            ("4x600m at 2:10-2:12 (75 sec rest)", "strict"),
            ("4x600m hard", "athlete_preferences"),
        ):
            with self.subTest(text=text, policy=policy):
                draft = parse(self.normalize(text, policy).prescription)
                self.assertFalse(draft.unresolved)
                self.assertTrue(draft.steps[0].skip_last_recovery)


if __name__ == "__main__":
    unittest.main()
