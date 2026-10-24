import unittest

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_workout


class TotalDistanceRunTests(unittest.TestCase):
    def event(self, text):
        return Event("synthetic", "total", "", "2030-03-01", text, "")

    def test_with_intervals_uses_approved_lap_bookends_and_preserves_total(self):
        text = "10 miles easy with 6 x 20 seconds fast/2 min easy"
        self.assertTrue(
            parse(
                normalize_workout(self.event(text), coaching_policy="strict").prescription
            ).unresolved
        )
        event = normalize_workout(self.event(text), coaching_policy="cj")
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        self.assertEqual(len(draft.steps), 3)
        warm, group, cool = draft.steps
        self.assertEqual((warm.kind, cool.kind), ("warm_up", "cool_down"))
        self.assertEqual((warm.unit, cool.unit), ("lap_button", "lap_button"))
        self.assertEqual(group.count, 6)
        self.assertEqual([s.duration for s in group.steps], [20, 120])
        self.assertIn("10 miles total", warm.note)
        self.assertIn("Finish 10 miles total", cool.note)
        self.assertIn("Added Lap", event.description)
        for profile in ("123", "coros:us:synthetic"):
            self.assertNotIn("error", review_item(profile, event))

    def test_metric_and_range_totals_keep_original_range_in_bookend_notes(self):
        text = "8-10 km easy including 4 x 30 seconds hard/90 seconds easy"
        draft = parse(normalize_workout(self.event(text), coaching_policy="cj").prescription)
        self.assertFalse(draft.unresolved)
        for bookend in (draft.steps[0], draft.steps[-1]):
            self.assertIn("10 km total", bookend.note)
            self.assertIn("8-10 km", bookend.note)

    def test_unknown_inner_instructions_explicit_bookends_and_recovery_opt_out_stay_blocked(self):
        for text in (
            "10 miles easy with 6 x 20 seconds fast/choose recovery",
            "Warm up 1 mile; 10 miles easy with 6 x 20 seconds fast/2 min easy",
            "10 miles easy with 6 x 20 seconds fast/2 min easy and more intervals",
            "10 miles easy with 4 x 3 mi at 6:30-6:40/mi with 90 sec rest recovery",
            "5 km easy with Run 30 min at 3:00-3:10/km",
        ):
            self.assertTrue(
                parse(
                    normalize_workout(self.event(text), coaching_policy="cj").prescription
                ).unresolved
            )
        self.assertTrue(
            parse(
                normalize_workout(
                    self.event("10 miles easy with 4 x 20 second hills"),
                    coaching_policy="cj",
                    recovery_choice="review",
                ).prescription
            ).unresolved
        )

    def test_terrain_on_total_run_is_retained_in_the_bookend_notes(self):
        event = normalize_workout(
            self.event("10 miles easy on trails with 4 x 20 seconds fast/2 min easy"),
            coaching_policy="cj",
        )
        draft = parse(event.prescription)
        self.assertFalse(draft.unresolved)
        for bookend in (draft.steps[0], draft.steps[-1]):
            self.assertIn("on trails", bookend.note)
