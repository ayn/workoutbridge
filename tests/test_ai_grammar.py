import unittest

from workoutbridge.ai import INSTRUCTIONS
from workoutbridge.coros import workout_payload as coros_payload
from workoutbridge.garmin import workout_payload as garmin_payload
from workoutbridge.parser import parse


class AIGrammarTests(unittest.TestCase):
    def test_instructions_advertise_current_executable_grammar(self):
        examples = (
            "Warm up 1.5 miles; Cool down 1 mile",
            "4 x 800 m in 3:00-3:05 sec with 90 sec rest recovery",
            "Run 3 miles tempo at 6:30-6:40/mi",
            "3 x 1.25 mi at 6:30-6:40/mi with 120 sec rest recovery",
            "3 x [Run 120 sec hard | Run 60 sec easy | Run 30 sec fast | Run 90 sec moderate]",
            "4 x 45 sec fast with 90 sec rest recovery",
            "4 x 30 sec uphill with lap recovery jog down",
            "Run 6 miles [distance note: 5-6 miles]",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIn(text, INSTRUCTIONS)
                draft = parse(text)
                self.assertFalse(draft.unresolved)
                garmin_payload("Synthetic grammar", "", draft)
                coros_payload("Synthetic grammar", "", draft)

    def test_approved_lap_policy_does_not_require_recovery_assumptions(self):
        self.assertIn("APPROVED RECOVERY POLICY", INSTRUCTIONS)
        self.assertIn(
            "do not list this approved policy as an assumption or unresolved item", INSTRUCTIONS
        )
        self.assertNotIn("No implicit Lap/recovery policy is enabled", INSTRUCTIONS)
        for text in (
            "4 x 800 m in 3:00-3:05 sec with lap recovery",
            "Rest until lap",
            "4 x [Run 45 sec hard | Rest until lap]",
        ):
            self.assertIn(text, INSTRUCTIONS)
            draft = parse(text)
            self.assertFalse(draft.unresolved)
            garmin_payload("Synthetic", "", draft)
            coros_payload("Synthetic", "", draft)
