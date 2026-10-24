import unittest

from workoutbridge.calendar import Event
from workoutbridge.coros import workout_payload as coros_payload
from workoutbridge.garmin import workout_payload as garmin_payload
from workoutbridge.parser import Repeat, Step, parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class RunShorthandTests(unittest.TestCase):
    def event(self, title, description=""):
        return Event("synthetic", "run-shorthand", "", "2030-02-01", title, description)

    def test_uphill_sprints_keep_final_recovery_and_transition(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            for text in (
                "8 miles + 5x 12s uphill sprints",
                "8 miles + 5 × 12 seconds uphill sprints",
            ):
                original = self.event("Run: " + text)
                normalized = normalize(original)
                draft = parse(normalized.prescription)
                self.assertFalse(draft.unresolved)
                self.assertEqual(
                    draft.steps,
                    (
                        Step("run", 8 * 1609.344, "meters", display_unit="mi"),
                        Step("run", None, "lap_button"),
                        Repeat(
                            5,
                            (
                                Step("run", 12, "seconds", note="uphill sprint"),
                                Step("rest", None, "lap_button"),
                            ),
                            skip_last_recovery=False,
                        ),
                    ),
                )
                self.assertIn(original.title, normalized.description)
                garmin = garmin_payload(original.title, normalized.description, draft)
                group = garmin["workoutSegments"][0]["workoutSteps"][2]
                self.assertFalse(group["skipLastRestStep"])
                self.assertEqual(group["workoutSteps"][0]["description"], "uphill sprint")
                coros = coros_payload(original.title, normalized.description, draft)
                self.assertEqual(coros["sections"][2]["repeats"], 5)
                self.assertEqual(coros["sections"][2]["sets"][1]["targetType"], 4)
                self.assertIn("uphill sprint", coros["courseDescription"])

    def test_uphill_sprints_opt_out_and_unknown_recovery_stay_blocked(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            event = self.event("Run: 8 miles + 5x12s uphill sprints")
            self.assertTrue(
                parse(normalize(event, recovery_choice="review").prescription).unresolved
            )
            for tail in (" with 30 sec recovery", " jog downhill", " at maximum heart rate"):
                event = self.event("Run: 8 miles + 5x12s uphill sprints" + tail)
                self.assertTrue(parse(normalize(event).prescription).unresolved)

    def test_fast_finish_splits_total_without_inventing_pace(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            original = self.event("Run - Long Run: 18 miles w/ last 6 miles fast")
            normalized = normalize(original)
            draft = parse(normalized.prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(
                draft.steps,
                (
                    Step("run", 12 * 1609.344, "meters", display_unit="mi"),
                    Step(
                        "run", 6 * 1609.344, "meters", note="last 6 miles fast", display_unit="mi"
                    ),
                ),
            )
            self.assertIn(original.title, normalized.description)
            garmin = garmin_payload(original.title, normalized.description, draft)
            for step in garmin["workoutSegments"][0]["workoutSteps"]:
                self.assertEqual(step["targetType"]["workoutTargetTypeKey"], "no.target")
            coros = coros_payload(original.title, normalized.description, draft)
            self.assertEqual(len(coros["sections"]), 2)
            self.assertIn("last 6 miles fast", coros["courseDescription"])

    def test_unsupported_fast_finish_and_sprint_bounds_stay_for_review(self):
        for text in (
            "18 miles w/ last 0 miles fast",
            "18 miles w/ last 18 miles fast",
            "18 miles w/ last 20 miles fast",
            "18 miles w/ last 6 miles fast at 6:00/mi",
            "18 miles w/ last 6 miles fast or easy",
            "8 miles + 0x12s uphill sprints",
            "8 miles + 101x12s uphill sprints",
            "8 miles + 5x0s uphill sprints",
            "8 miles + 5x3601s uphill sprints",
        ):
            with self.subTest(text=text):
                self.assertTrue(
                    parse(normalize_workout(self.event("Run: " + text)).prescription).unresolved
                )

    def test_substantive_description_wins_over_title(self):
        for normalize in (normalize_workout, normalize_finalsurge):
            event = self.event(
                "Run - Long Run: 18 miles w/ last 6 miles fast", "Coach will clarify"
            )
            self.assertTrue(parse(normalize(event).prescription).unresolved)
            event = self.event(
                "Run: 8 miles + 5x12s uphill sprints", "8 miles + 3x10s uphill sprints"
            )
            draft = parse(normalize(event).prescription)
            self.assertFalse(draft.unresolved)
            self.assertEqual(draft.steps[-1].count, 3)
            self.assertEqual(draft.steps[-1].steps[0].duration, 10)

    def test_finalsurge_long_run_metadata_does_not_hide_title(self):
        event = self.event(
            "Run - Long Run: 18 miles w/ last 6 miles fast",
            "Workout: Run - Long Run\nPlanned: 18 mi",
        )
        draft = parse(normalize_workout(event).prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)

    def test_incomplete_warmup_description_does_not_hide_fast_finish(self):
        event = self.event("Run - Long Run: 18 miles w/ last 6 miles fast", "Warm up 1 miles")
        self.assertTrue(parse(normalize_finalsurge(event).prescription).unresolved)
