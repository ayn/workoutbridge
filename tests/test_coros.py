import unittest

from workoutbridge.coros import workout_payload
from workoutbridge.parser import Draft, Repeat, Step, parse


class CorosPayloadTests(unittest.TestCase):
    def test_lap_warmup_native_repeats_pace_and_recovery(self):
        draft = parse(
            "warm up until lap; 2 x 200 m in 60-64 sec with 2 min easy recovery; "
            "cool down until lap"
        )
        payload = workout_payload("Test intervals", "Synthetic workout", draft)
        self.assertEqual(payload["sportType"], 1)
        self.assertEqual(payload["sections"][0], {"sectionType": 1, "targetType": 4})
        group = payload["sections"][1]
        self.assertEqual(group["repeats"], 2)
        self.assertTrue(group["intervalGroup"])
        self.assertEqual(
            group["sets"][0],
            {
                "sectionType": 2,
                "targetType": 1,
                "targetValue": 200,
                "intensityType": 2,
                "intensityValueStart": 300,
                "intensityValueEnd": 320,
            },
        )
        self.assertEqual(group["sets"][1], {"sectionType": 2, "targetType": 2, "targetValue": 120})
        self.assertEqual(payload["sections"][-1], {"sectionType": 4, "targetType": 4})
        self.assertIn("1:00-1:04", payload["courseDescription"])
        self.assertIn(draft.original_text, payload["courseDescription"])

    def test_no_invented_intensity_and_round_distance_to_integer_meters(self):
        payload = workout_payload("Easy run", "", parse("run 1 mi easy"))
        self.assertEqual(
            payload["sections"], [{"sectionType": 2, "targetType": 1, "targetValue": 1609}]
        )
        self.assertIn("easy", payload["courseDescription"])

    def test_skip_final_recovery_is_preserved(self):
        run, rest = Step("run", 200, "meters"), Step("rest", None, "lap_button")
        draft = Draft("Repeat twice, omit final recovery", (Repeat(2, (run, rest)),), ())
        sections = workout_payload("Test", "", draft)["sections"]
        self.assertEqual(sections[0]["repeats"], 1)
        self.assertEqual(len(sections[0]["sets"]), 2)
        self.assertEqual(sections[1], {"sectionType": 2, "targetType": 1, "targetValue": 200})

    def test_one_repeat_with_skip_has_no_recovery(self):
        draft = Draft(
            "One rep", (Repeat(1, (Step("run", 60, "seconds"), Step("rest", 30, "seconds"))),), ()
        )
        self.assertEqual(
            workout_payload("Test", "", draft)["sections"],
            [{"sectionType": 2, "targetType": 2, "targetValue": 60}],
        )

    def test_unresolved_and_empty_are_rejected(self):
        for draft in [parse("unknown exercise"), Draft("", (), ())]:
            with self.assertRaises(ValueError):
                workout_payload("Test", "", draft)

    def test_bad_title_rejected_without_truncation(self):
        for title in ["", " ", "x" * 101]:
            with self.assertRaises(ValueError):
                workout_payload(title, "", parse("run 10 min"))

    def test_unsupported_repeats_require_review(self):
        run = Step("run", 200, "meters")
        for group in [
            Repeat(21, (run,)),
            Repeat(0, (run,)),
            Repeat(2, ()),
            Repeat(2, (Step("warm_up", 60, "seconds"),)),
            Repeat(2, (Repeat(2, (run,)),)),
        ]:
            with self.assertRaises(ValueError):
                workout_payload("Test", "", Draft("Test", (group,), ()))

    def test_invalid_targets_require_review(self):
        for step in [
            Step("run", 0, "seconds"),
            Step("run", float("nan"), "meters"),
            Step("run", 1, "lap_button"),
            Step("run", 60, "seconds", speed_min=3),
            Step("run", 60, "seconds", speed_min=0.1, speed_max=0.2),
            Step("run", 60, "seconds", speed_min=4, speed_max=3),
        ]:
            with self.assertRaises(ValueError):
                workout_payload("Test", "", Draft("Test", (step,), ()))


if __name__ == "__main__":
    unittest.main()
