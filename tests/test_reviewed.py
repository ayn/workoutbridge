import unittest

from workoutbridge.calendar import Event
from workoutbridge.publishing import event_payload
from workoutbridge.reviewed import review_easy_run


class ReviewedTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "example", "", "2027-01-05", text, "")

    def test_high_range_original_notes_and_lap_bookends(self):
        e = review_easy_run(self.event("5-7 miles easy"), range_choice="higher")
        payload = event_payload(e)
        self.assertIn("5-7 miles easy", payload["description"])
        steps = payload["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[1]["endConditionValue"], 7 * 1609.344)
        self.assertEqual(steps[0]["stepType"]["stepTypeKey"], "warmup")
        self.assertEqual(steps[-1]["stepType"]["stepTypeKey"], "cooldown")
        self.assertEqual(steps[0]["endCondition"]["conditionTypeKey"], "lap.button")
        self.assertEqual(steps[-1]["endCondition"]["conditionTypeKey"], "lap.button")

    def test_hills_native_repeat_and_explicit_lap_recovery_policy(self):
        e = self.event("5-7 miles easy plus 3 x 15 second hills")
        with self.assertRaises(ValueError):
            review_easy_run(e, range_choice="higher")
        e = review_easy_run(e, range_choice="higher", recovery_choice="lap")
        group = event_payload(e)["workoutSegments"][0]["workoutSteps"][2]
        self.assertEqual(group["numberOfIterations"], 3)
        self.assertEqual(group["workoutSteps"][0]["endConditionValue"], 15)
        self.assertEqual(group["workoutSteps"][0]["description"], "Hills")
        self.assertEqual(group["workoutSteps"][1]["endCondition"]["conditionTypeKey"], "lap.button")
        self.assertTrue(group["skipLastRestStep"])

    def test_conditional_or_unrecognized_text_blocked(self):
        for text in (
            "rest",
            "easy jog if feeling good",
            "5 miles with strides",
            "7-5 miles easy",
            "5 miles easy; cool down 1 mile",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                review_easy_run(self.event(text), range_choice="higher")

    def test_source_identity_and_description_preserved(self):
        source = Event("synthetic", "example", "", "2027-01-05", "Easy day", "9 miles easy/mod")
        result = review_easy_run(source, range_choice="higher")
        self.assertEqual(result.uid, source.uid)
        self.assertEqual(result.title, source.title)
        self.assertIn(source.description, result.description)
        self.assertIn("easy/mod", event_payload(result)["description"])

    def test_existing_review_and_cancellation_blocked(self):
        from dataclasses import replace

        e = review_easy_run(self.event("5 miles easy"), range_choice="higher")
        with self.assertRaises(ValueError):
            review_easy_run(e, range_choice="higher")
        with self.assertRaises(ValueError):
            review_easy_run(
                replace(self.event("5 miles easy"), cancelled=True), range_choice="higher"
            )
