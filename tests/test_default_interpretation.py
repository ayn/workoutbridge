import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout


class DefaultInterpretationTests(unittest.TestCase):
    def test_every_source_uses_documented_conversion_defaults_without_coach_identity(self):
        for normalizer in (normalize_workout, normalize_finalsurge):
            for text in (
                "3x1200",
                "3x (1 hard/1 easy)",
                "5-6 miles easy",
                "4x800m at 2:55-3:00 (2:30-3:00 rest)",
                "4 miles tempo at ~ 6:40/mi",
                "9 miles easy with 3 x 20 sec fast/2 min easy",
                "5-6 miles easy if feeling okay",
            ):
                with self.subTest(normalizer=normalizer.__name__, text=text):
                    original = Event("synthetic", "defaults", "", "2030-01-01", "Run: " + text, "")
                    event = normalizer(original)
                    explicit = normalizer(original, coaching_policy="athlete_preferences")
                    self.assertEqual(event, explicit)
                    self.assertFalse(parse(event.prescription).unresolved)
                    self.assertIn(text, event.description)
                    for profile in ("123", "coros:us:synthetic"):
                        self.assertNotIn("error", review_item(profile, event))
                    self.assertTrue(
                        parse(
                            normalizer(original, coaching_policy="strict").prescription
                        ).unresolved
                    )

    def test_default_still_rejects_alternatives_and_honors_recovery_opt_out(self):
        for text in ("5-6 miles or cross train", "3x1200 or 4x800", "3x1200 at 160 bpm"):
            event = Event("synthetic", "defaults", "", "2030-01-01", "Run: " + text, "")
            self.assertTrue(parse(normalize_workout(event).prescription).unresolved)
        event = Event("synthetic", "defaults", "", "2030-01-01", "Run: 3x1200", "")
        self.assertTrue(
            parse(normalize_workout(event, recovery_choice="review").prescription).unresolved
        )
