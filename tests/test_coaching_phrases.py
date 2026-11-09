"""Synthetic varied coaching clauses, never production prescriptions."""

import unittest

from workoutbridge.calendar import Event
from workoutbridge.parser import Repeat, Step, parse
from workoutbridge.prescriptions import normalize_workout


class CoachingPhraseTests(unittest.TestCase):
    def normalize(self, text, policy="athlete_preferences"):
        original = Event("synthetic", "coaching-grammar", "", "2032-04-08", "Run: Session", text)
        normalized = normalize_workout(original, coaching_policy=policy)
        return normalized, parse(normalized.prescription)

    def test_singular_mile_slow_recovery_and_effort_cue(self):
        text = (
            "2 miles easy, 4 x 1 mile fast with 90 sec slow recovery (think 5k), "
            "6 x 20 seconds fast/90 sec easy, 1.5 miles easy. Optional easy double."
        )
        normalized, draft = self.normalize(text)
        self.assertFalse(draft.unresolved, draft.unresolved)
        groups = [s for s in draft.steps if isinstance(s, Repeat)]
        self.assertEqual([s.count for s in groups], [4, 6])
        self.assertEqual(groups[0].steps[0].duration, 1609.344)
        self.assertIn("think 5k", groups[0].steps[0].note)
        self.assertEqual(groups[0].steps[1].duration, 90)
        self.assertEqual(groups[0].steps[1].label, "slow")
        self.assertFalse(groups[0].skip_last_recovery)
        self.assertIn("Optional easy double", normalized.description)
        self.assertIn(text, normalized.description)

    def test_parenthesized_total_float_intervals_have_lap_bookends(self):
        text = "24 miles easy/mod (2 x 5 miles at M effort with 1 mile float recovery)"
        normalized, draft = self.normalize(text)
        self.assertFalse(draft.unresolved, draft.unresolved)
        self.assertEqual(len(draft.steps), 3)
        self.assertEqual((draft.steps[0].kind, draft.steps[0].unit), ("warm_up", "lap_button"))
        group = draft.steps[1]
        self.assertEqual(group.count, 2)
        self.assertEqual([s.duration for s in group.steps], [5 * 1609.344, 1609.344])
        self.assertIn("m effort", (group.steps[0].label or "") + group.steps[0].note)
        self.assertEqual(group.steps[1].label, "float")
        self.assertFalse(group.skip_last_recovery)
        self.assertEqual((draft.steps[-1].kind, draft.steps[-1].unit), ("cool_down", "lap_button"))
        self.assertIn("Finish 24 miles total", draft.steps[-1].note)
        self.assertIn(text, normalized.description)
        self.assertTrue(self.normalize(text, "strict")[1].unresolved)

    def test_acceleration_footer_builds_explicit_meter_phases(self):
        text = (
            "Run 2.5 miles east\n6 x 180 acceleration strides/jog 220 as recovery\n"
            "1 mile easy\nFor the strides run the pickup is every 60M- "
            "start 2k effort/1200M/600M effort"
        )
        normalized, draft = self.normalize(text)
        self.assertFalse(draft.unresolved, draft.unresolved)
        group = next(s for s in draft.steps if isinstance(s, Repeat))
        self.assertEqual(group.count, 6)
        self.assertEqual([s.duration for s in group.steps], [60, 60, 60, 220])
        self.assertEqual([s.unit for s in group.steps], ["meters"] * 4)
        for step, cue in zip(group.steps, ["2k effort", "1200M effort", "600M effort"]):
            self.assertIn(cue.lower(), step.note.lower())
            self.assertIsNone(step.speed_min)
        self.assertEqual(group.steps[-1].kind, "rest")
        self.assertEqual(group.steps[-1].label, "jog")
        self.assertFalse(group.skip_last_recovery)
        self.assertIn("east", normalized.description)
        self.assertIn("easy", (draft.steps[0].label or "") + draft.steps[0].note)
        self.assertIn("east", draft.steps[0].note)

    def test_targeted_ladder_and_bounded_prose_notes(self):
        footer = (
            "The paces get faster as the distances get shorter. "
            "This is a relaxed workout to get the legs going. My track athletes really enjoyed this one."
        )
        text = (
            "Warm up 1.5 miles + strides; 2 mile @ (6:40-50 min pace) 4-5 min rest; "
            "1000M @ 3:30 (90 sec rest); 500M @ mile pace (2:15 min rest); "
            "300M @ fast; Cool down 1.5 mile\n" + footer
        )
        normalized, draft = self.normalize(text)
        self.assertFalse(draft.unresolved, draft.unresolved)
        singles = [s for s in draft.steps if isinstance(s, Step)]
        paced = next(s for s in singles if s.duration == 2 * 1609.344)
        self.assertAlmostEqual(paced.speed_min, 1609.344 / 410)
        self.assertAlmostEqual(paced.speed_max, 1609.344 / 400)
        rests = [s for s in singles if s.kind == "rest"]
        self.assertEqual([s.duration for s in rests], [300, 90, 135])
        self.assertIn("4-5 min rest", rests[0].note)
        timed_rep = next(s for s in singles if s.duration == 1000)
        self.assertAlmostEqual(timed_rep.speed_min, 1000 / 210)
        effort_rep = next(s for s in singles if s.duration == 500)
        self.assertIn("mile pace", (effort_rep.label or "") + effort_rep.note)
        self.assertIsNone(effort_rep.speed_min)
        self.assertIn(footer, normalized.description)
        self.assertIn(footer, draft.steps[-1].note)

    def test_east_without_acceleration_context_still_needs_review(self):
        for policy in ("athlete_preferences", "strict"):
            self.assertTrue(self.normalize("Run 4.5 miles east", policy)[1].unresolved)

    def test_unknown_acceleration_and_extra_instructions_still_need_review(self):
        for text in (
            "Run 4 miles east and stop at the east gate",
            "8 miles easy (2 x 5 miles at M effort with 1 mile float recovery)",
            "3 x 1 mile fast with 2 min slow recovery (think 5k and add a sprint)",
            "4 x 150 acceleration strides/jog 200 as recovery\n"
            "For the strides run the pickup is every 40M- start 3k effort/mile effort/800M effort",
            "Warm up 2 miles; 300m fast; Cool down 2 miles\n"
            "The paces will get faster as the distance gets shorter. Add 3 more reps.",
            "2 mile @ (6:40-10 min pace) 4-5 min rest",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.normalize(text)[1].unresolved)


if __name__ == "__main__":
    unittest.main()
