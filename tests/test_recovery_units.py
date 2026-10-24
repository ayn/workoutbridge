import unittest

from workoutbridge.coros import workout_payload as coros_payload
from workoutbridge.garmin import workout_payload as garmin_payload
from workoutbridge.parser import parse


class RecoveryUnitTests(unittest.TestCase):
    def test_explicit_recovery_units_compile_to_the_same_duration(self):
        for unit, amount in (
            ("min", 2),
            ("minutes", 2),
            ("seconds", 120),
            ("hours", 0.03333333333333333),
        ):
            for work in (
                "3 x 1.25 mi at 6:30-6:40/mi",
                "3 x 800 m in 3:00-3:05 sec",
                "3 x 400 m hard",
                "3 x 45 sec fast",
            ):
                text = f"{work} with {amount} {unit} rest recovery"
                with self.subTest(text=text):
                    draft = parse(text)
                    self.assertFalse(draft.unresolved)
                    self.assertAlmostEqual(draft.steps[0].steps[1].duration, 120)
                    garmin_payload("Synthetic recovery", "", draft)
                    coros_payload("Synthetic recovery", "", draft)

    def test_unknown_negative_and_unbounded_recovery_units_stay_blocked(self):
        for rest in ("2 miles", "-2 min", "25 hours", "0 seconds"):
            self.assertTrue(
                parse("3 x 1.25 mi at 6:30-6:40/mi with " + rest + " rest recovery").unresolved
            )
