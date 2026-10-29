import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_workout


class SlashEffortSetTests(unittest.TestCase):
    def normalize(self, text, policy="athlete_preferences"):
        event = Event("synthetic", "slash-sets", "", "2030-03-01", "Run: Sets", text)
        return normalize_workout(event, coaching_policy=policy)

    def test_repeated_effort_sets_and_note_only_walk(self):
        block = (
            "2 km @ HMP race pace/ easy 3 min jog recovery\n"
            "3 x 90 sec @ 10k effort/45 sec easy - 45 sec walk recovery after the set\n"
        )
        event = self.normalize(
            "Warm Up 1 km\n" + block * 2 + "2 km @ HMP race pace\nCool down 1 km"
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 9)
        self.assertEqual(draft.steps[1].label, "half marathon pace")
        self.assertEqual(draft.steps[2].duration, 180)
        self.assertEqual(draft.steps[2].kind, "rest")
        self.assertEqual(draft.steps[3], draft.steps[6])
        group = draft.steps[3]
        self.assertIsInstance(group, Repeat)
        self.assertEqual(group.count, 3)
        self.assertEqual([s.duration for s in group.steps], [90, 45])
        self.assertFalse(group.skip_last_recovery)
        self.assertEqual(group.steps[0].label, "10k effort")
        self.assertIn("45 sec walk recovery after the set", group.steps[0].note)
        self.assertTrue(all(s.speed_min is None for s in group.steps))
        for profile in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(profile, event))

    def test_explicit_slash_recovery_without_walk_works_in_strict_mode(self):
        event = self.normalize("2 km @ HMP race pace/ easy 3 min jog recovery", "strict")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 2)
        self.assertEqual(draft.steps[-1].duration, 180)

    def test_walk_note_policy_and_unknown_tails_require_review(self):
        for text, policy in (
            ("3 x 90 sec @ 10k effort/45 sec easy - 45 sec walk recovery after the set", "strict"),
            ("3 x 90 sec @ 10k effort/45 sec easy - swim after the set", "athlete_preferences"),
            ("2 km @ HMP race pace/ easy jog recovery", "strict"),
            ("2 km @ HMP race pace/ easy 3 min jog recovery then sprint", "strict"),
        ):
            self.assertTrue(parse(self.normalize(text, policy).prescription).unresolved)
