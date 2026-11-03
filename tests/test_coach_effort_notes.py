import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class CoachEffortNoteTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "effort-notes", "", "2030-04-01", "Run: Synthetic session", text)

    def test_relative_effort_cues_are_notes_without_invented_numeric_targets(self):
        text = "2 miles easy, 6 x 2 min fast/1 min easy (think 1-hour effort), 2 min easy, 3 x 20 seconds fast/70 seconds easy (think mile), 1 mile easy. Optional easy double"
        event = normalize_workout(self.event(text))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        groups = [s for s in draft.steps if isinstance(s, Repeat)]
        self.assertEqual([s.count for s in groups], [6, 3])
        self.assertEqual([s.steps[0].duration for s in groups], [120, 20])
        self.assertEqual([s.steps[1].duration for s in groups], [60, 70])
        self.assertIn("think 1-hour effort", groups[0].steps[0].note)
        self.assertIn("think mile", groups[1].steps[0].note)
        self.assertTrue(all(not g.skip_last_recovery for g in groups))
        self.assertIn("Optional easy double", draft.steps[-1].note)
        for step in [s for s in draft.steps if not isinstance(s, Repeat)] + [
            g.steps[0] for g in groups
        ]:
            self.assertIsNone(step.speed_min)
            self.assertIsNone(step.speed_max)
        for account in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(account, event))

    def test_marathon_effort_percentage_remains_a_note_on_the_complete_run(self):
        event = normalize_workout(
            self.event("16 miles easy/mod over hills, looking for 88-93% of M effort")
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 1)
        step = draft.steps[0]
        self.assertEqual(step.duration, 16 * 1609.344)
        self.assertIn("88-93% of M effort", step.note)
        self.assertIn("over hills", step.label or step.note)
        self.assertIsNone(step.speed_min)
        self.assertIsNone(step.speed_max)

    def test_executable_parentheticals_and_other_numeric_targets_stay_for_review(self):
        for text in (
            "6 x 2 min fast/1 min easy (think 1-hour effort and add 2 reps)",
            "16 miles easy, looking for 150-160 bpm",
            "16 miles easy, looking for 4:30/km",
        ):
            self.assertTrue(parse(normalize_workout(self.event(text)).prescription).unresolved)
