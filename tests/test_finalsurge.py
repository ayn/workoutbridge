import unittest

from workoutbridge.calendar import Event
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout
from workoutbridge.publishing import event_payload


class FinalSurgeTests(unittest.TestCase):
    def test_generic_title_or_description_implies_hill_recovery(self):
        for in_description in (False, True):
            original = Event(
                "synthetic-google",
                "hill",
                "",
                "2027-01-06",
                "Hill session" if in_description else "4 x 1' hill hard",
                "4 x 1' hill hard" if in_description else "",
            )
            event = normalize_workout(original)
            group = event_payload(event)["workoutSegments"][0]["workoutSteps"][0]
            self.assertEqual(group["numberOfIterations"], 4)
            self.assertEqual(group["workoutSteps"][0]["endConditionValue"], 60)
            self.assertEqual(group["workoutSteps"][0]["description"], "Hills hard")
            self.assertEqual(
                group["workoutSteps"][1]["endCondition"]["conditionTypeKey"], "lap.button"
            )
            with self.assertRaises(ValueError):
                event_payload(normalize_workout(original, recovery_choice="review"))

    def test_generic_explicit_recovery_not_replaced(self):
        original = self.event("4 x 200 m in 60-65 sec with 90 sec easy recovery")
        from dataclasses import replace

        original = replace(original, description="")
        normalized = normalize_workout(original)
        self.assertEqual(normalized, original)
        group = parse(normalized.prescription).steps[0]
        self.assertEqual(group.steps[1].duration, 90)
        self.assertEqual(group.steps[1].kind, "run")

    def test_explicit_unknown_hill_recovery_stays_for_review(self):
        from dataclasses import replace

        event = replace(self.event("4 x 1' hill hard, jog down recovery"), description="")
        self.assertTrue(parse(normalize_workout(event).prescription).unresolved)

    def event(self, title=" Run: 5 miles + 3x200m smooth + 2x100m", extra=""):
        return Event(
            "synthetic-fs",
            "synthetic-uid",
            "",
            "2027-01-05",
            title,
            "Workout: Run\n\nPlanned: 5.5 mi" + extra,
        )

    def test_title_distance_and_native_groups_with_approved_lap_recovery(self):
        original = self.event()
        event = normalize_finalsurge(original)
        payload = event_payload(event)
        steps = payload["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[0]["endConditionValue"], 5 * 1609.344)
        self.assertEqual(steps[1]["endCondition"]["conditionTypeKey"], "lap.button")
        self.assertEqual([s["numberOfIterations"] for s in steps[2:]], [3, 2])
        self.assertEqual(steps[2]["workoutSteps"][0]["description"], "smooth")
        self.assertEqual(steps[2]["workoutSteps"][0]["endConditionValue"], 200)
        self.assertEqual(
            steps[2]["workoutSteps"][1]["endCondition"]["conditionTypeKey"], "lap.button"
        )
        self.assertIn(original.title, payload["description"])
        self.assertIn(original.description, payload["description"])
        self.assertEqual(event.uid, original.uid)
        self.assertEqual(event.title, original.title)
        self.assertFalse(any(s["stepType"]["stepTypeKey"] == "cooldown" for s in steps))

    def test_missing_recovery_can_require_review(self):
        event = normalize_finalsurge(self.event(), recovery_choice="review")
        self.assertTrue(parse(event.prescription).unresolved)
        with self.assertRaises(ValueError):
            event_payload(event)

    def test_explicit_description_is_not_discarded_for_title(self):
        event = normalize_finalsurge(
            self.event(extra="\n\nWarm up 2 miles; Run 10 min hard; Cool down 1 miles"),
            recovery_choice="lap",
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual([s.kind for s in draft.steps], ["warm_up", "run", "cool_down"])
        self.assertEqual(draft.steps[1].duration, 600)

    def test_unsupported_detail_blocks_instead_of_using_title(self):
        event = normalize_finalsurge(
            self.event(extra="\nCoach says change reps depending on fatigue"),
            recovery_choice="lap",
        )
        self.assertTrue(parse(event.prescription).unresolved)

    def test_warmup_only_description_does_not_hide_main_workout(self):
        for title in ("Run: 5x800m", "Run: Fartlek", "Run: 3 mile tempo"):
            event = self.event(title, extra="\nWarm up 1 miles")
            with self.subTest(title=title), self.assertRaises(ValueError):
                event_payload(normalize_finalsurge(event))

    def test_plain_run_and_timed_fartlek(self):
        easy = normalize_finalsurge(self.event("Run: 12 miles moderate"))
        self.assertFalse(parse(easy.prescription).unresolved)
        self.assertEqual(parse(easy.prescription).steps[0].label, "moderate")
        fartlek = normalize_finalsurge(self.event("Run: 5 miles + 3x(30s hard; 45s moderate)"))
        draft = parse(fartlek.prescription)
        self.assertFalse(draft.unresolved)
        group = draft.steps[-1]
        self.assertEqual(group.count, 3)
        self.assertEqual([s.duration for s in group.steps], [30, 45])
        self.assertEqual([s.kind for s in group.steps], ["run", "run"])

    def test_non_running_cancelled_and_unknown_clauses_stay_blocked(self):
        from dataclasses import replace

        for event in (
            self.event("Bike: 5 miles"),
            replace(self.event(), cancelled=True),
            self.event("Run: 5 miles + coach will explain"),
            self.event("Run: 5 miles + 0x200m"),
        ):
            with self.subTest(title=event.title), self.assertRaises(ValueError):
                event_payload(normalize_finalsurge(event, recovery_choice="lap"))

    def test_existing_review_is_preserved(self):
        from dataclasses import replace

        event = replace(self.event(), structured_text="Run 10 min")
        self.assertEqual(normalize_finalsurge(event), event)
