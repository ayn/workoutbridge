import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import Repeat, parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class DistanceRecoveryLadderTests(unittest.TestCase):
    def event(self, text, title="Run: Synthetic session"):
        return Event("synthetic", "ladder", "", "2030-05-01", title, text)

    def test_unitless_distance_recoveries_preserve_effort_cues_and_all_reps(self):
        text = (
            "2 miles easy, 6 x 600 fast with 300 easy recovery "
            "(think 10k effort, pushing a little as you go), "
            "3 x 150 fast/150 easy (think mile), 1 mile easy. Optional easy double"
        )
        event = normalize_workout(self.event(text))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        groups = [s for s in draft.steps if isinstance(s, Repeat)]
        self.assertEqual([g.count for g in groups], [6, 3])
        self.assertTrue(all(not g.skip_last_recovery for g in groups))
        self.assertEqual([[s.duration for s in g.steps] for g in groups], [[600, 300], [150, 150]])
        self.assertTrue(all(s.unit == "meters" for g in groups for s in g.steps))
        self.assertIn("pushing a little as you go", groups[0].steps[0].note)
        self.assertIn("think mile", groups[1].steps[0].note)
        self.assertTrue(
            all(s.speed_min is None and s.speed_max is None for g in groups for s in g.steps)
        )
        for account in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(account, event))
        self.assertTrue(
            parse(
                normalize_workout(self.event(text), coaching_policy="strict").prescription
            ).unresolved
        )

    def test_ladder_with_ten_explicit_phases_preserves_every_phase(self):
        phases = [
            "45 sec fast",
            "45 sec easy",
            "90 sec fast",
            "90 sec easy",
            "150 sec fast",
            "150 sec easy",
            "90 sec fast",
            "90 sec easy",
            "45 sec fast",
            "120 sec easy",
        ]
        event = normalize_workout(self.event("3 x (" + "/".join(phases) + ")"))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(draft.steps[0].count, 3)
        self.assertEqual(
            [s.duration for s in draft.steps[0].steps], [45, 45, 90, 90, 150, 150, 90, 90, 45, 120]
        )
        self.assertFalse(draft.steps[0].skip_last_recovery)
        for account in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(account, event))

    def test_finalsurge_fartlek_metadata_and_bounded_clock_typo(self):
        text = "Workout: Run - Fartlek\n\n1 mi wu; 3 x (2:oo fast/1:00 easy); 1 mi cd"
        event = normalize_finalsurge(self.event(text, "Run - Fartlek: Synthetic ladder"))
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        group = next(s for s in draft.steps if isinstance(s, Repeat))
        self.assertEqual([s.duration for s in group.steps], [120, 60])
        self.assertIn("2:oo", event.description)
        for account in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(account, event))

    def test_unknown_tails_missing_phases_and_excessive_groups_still_need_review(self):
        for text in (
            "6 x 600 fast with 300 easy recovery (think 10k effort and add 2 reps)",
            "3 x 150 fast/150 easy then add hills",
            "3 x (45 sec fast/45 sec easy/)",
            "3 x (" + "/".join(["45 sec fast"] * 17) + ")",
            "3 x (2:oo swim/1:00 easy)",
        ):
            self.assertTrue(
                parse(normalize_workout(self.event(text)).prescription).unresolved, text
            )

    def test_rest_or_run_is_still_an_athlete_decision(self):
        event = normalize_finalsurge(self.event("Workout: Rest Day", "Rest Day: Rest or easy run"))
        self.assertIn("error", review_item("123", event))
