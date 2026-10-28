import unittest
from datetime import date

from workoutbridge.calendar import import_calendar
from workoutbridge.cli import review_item
from workoutbridge.coros_publishing import event_values
from workoutbridge.parser import parse
from workoutbridge.prescriptions import normalize_finalsurge, normalize_workout
from workoutbridge.publishing import approval_token, event_key, event_payload


class CyclingTests(unittest.TestCase):
    def event(self, title, description="", extra=""):
        from icalendar import Calendar
        from icalendar import Event as ICalEvent

        cal = Calendar()
        cal.add("version", "2.0")
        ev = ICalEvent()
        ev.add("uid", "synthetic-cycle")
        ev.add("dtstart", date(2030, 1, 2))
        ev.add("summary", title)
        ev.add("description", description)
        if extra:
            ev.add("X-WORKOUTBRIDGE-SPORT", extra)
        cal.add_component(ev)
        return import_calendar(
            cal.to_ical(),
            source="synthetic",
            timezone="UTC",
            start=date(2030, 1, 1),
            end=date(2030, 1, 10),
        )[0]

    def test_final_surge_bike_metadata_and_title_become_native_cycling(self):
        event = normalize_finalsurge(
            self.event("Bike: 42 min easy", "Workout: Bike\n\nPlanned: 0:42:00")
        )
        result = review_item("synthetic", event)
        self.assertNotIn("error", result)
        self.assertEqual(result["draft"]["sport"], "cycling")
        payload = result["payload"]
        self.assertEqual(payload["sportType"], {"sportTypeId": 2, "sportTypeKey": "cycling"})
        self.assertEqual(payload["workoutSegments"][0]["sportType"], payload["sportType"])
        self.assertEqual(
            payload["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"], 2520
        )
        coros = event_values(event)["course"]
        self.assertEqual(coros["sportType"], 2)
        self.assertEqual(coros["sections"][0]["targetValue"], 2520)

    def test_cycling_duration_distance_and_explicit_interval_steps(self):
        event = normalize_workout(
            self.event(
                "Cycling intervals",
                "Warm up 8 min; 3 x 4 min hard with 90 sec easy recovery; Cool down 6 min",
            )
        )
        result = review_item("synthetic", event)
        self.assertNotIn("error", result)
        steps = result["payload"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[1]["numberOfIterations"], 3)
        self.assertEqual(steps[1]["workoutSteps"][0]["endConditionValue"], 240)
        self.assertEqual(steps[1]["workoutSteps"][1]["endConditionValue"], 90)
        distance = normalize_workout(self.event("Bike: 18 km easy"))
        self.assertEqual(
            event_payload(distance)["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"],
            18000,
        )

    def test_multiline_cycling_groups_preserve_explicit_time_and_distance(self):
        description = (
            "Workout: Bike\n\nWarm up 8 mins\n5x (4 mins hard; 1.5 mi easy)\nCool Down 6 mins"
        )
        event = normalize_finalsurge(self.event("Bike: Intervals", description))
        result = review_item("synthetic", event)
        self.assertNotIn("error", result)
        self.assertEqual(result["draft"]["sport"], "cycling")
        steps = result["payload"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[0]["endConditionValue"], 480)
        self.assertEqual(steps[1]["numberOfIterations"], 5)
        phases = steps[1]["workoutSteps"]
        self.assertEqual(phases[0]["endConditionValue"], 240)
        self.assertEqual(phases[1]["endConditionValue"], 2414.016)
        self.assertEqual(phases[1]["endCondition"]["conditionTypeKey"], "distance")
        self.assertEqual(steps[2]["endConditionValue"], 360)
        self.assertEqual(len(steps), 3)
        self.assertEqual(result["payload"]["description"], description)
        coros = event_values(event)["course"]
        self.assertEqual(coros["sportType"], 2)
        run = review_item("synthetic", normalize_workout(self.event("Run: 4 miles")))
        self.assertNotIn("error", run)
        self.assertEqual(run["payload"]["sportType"]["sportTypeId"], 1)

    def test_generic_cycling_groups_preserve_minutes_and_strict_policy(self):
        event = normalize_workout(
            self.event("Bike: Intervals", "WU 7 min\n3 x (5 mins hard; 2 mins easy)\nCD 4 min"),
            coaching_policy="strict",
        )
        result = review_item("synthetic", event)
        self.assertNotIn("error", result)
        steps = result["payload"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[1]["numberOfIterations"], 3)
        self.assertEqual(steps[1]["workoutSteps"][1]["endConditionValue"], 120)
        self.assertEqual(steps[1]["workoutSteps"][1]["endCondition"]["conditionTypeKey"], "time")

    def test_unknown_cycling_group_instructions_stay_in_review(self):
        for body in (
            "3 x (4 min hard; 2 easy)",
            "3 x (4 min hard at 180 watts; 2 min easy)",
            "3 x (4 min hard; 2 min easy) then swim 10 min",
            "3 x (Run 4 min hard; 2 min easy)",
            "3 x (4 min hard; 2 min easy",
        ):
            with self.subTest(body=body):
                event = normalize_workout(self.event("Bike: Intervals", "WU 7 min\n" + body))
                self.assertIn("error", review_item("synthetic", event))

    def test_explicit_cycling_section_preserves_notes_and_sport(self):
        notes = "Keep it comfortable.\n[WorkoutBridge]\nRide 35 min easy\n[/WorkoutBridge]"
        event = normalize_workout(self.event("Recovery session", notes, "cycling"))
        self.assertEqual(event.sport, "cycling")
        self.assertEqual(event_payload(event)["description"], notes)
        self.assertEqual(event_values(event)["course"]["sportType"], 2)

    def test_conflicting_and_unsupported_sports_and_targets_cannot_become_runs(self):
        for title, description in [
            ("Swim: 25 min", "Run 25 min"),
            ("Strength Training", "Run 10 min"),
            ("Bike: 30 min", "Workout: Run\nRun 30 min"),
            ("Run or bike", "Run 30 min"),
            ("Bike: 30 min", "Ride 30 min at 200 watts"),
            ("Bike: 5 strides", "5 strides with lap recovery"),
        ]:
            with self.subTest(title=title, description=description):
                event = normalize_workout(self.event(title, description))
                self.assertIn("error", review_item("synthetic", event))

    def test_running_payload_and_identity_stay_stable_but_approval_binds_sport(self):
        from dataclasses import replace

        run = normalize_workout(self.event("Run: 20 min easy"))
        self.assertEqual(event_payload(run)["sportType"]["sportTypeId"], 1)
        ride = replace(
            run, title="Bike: 20 min easy", structured_text="Ride 20 min easy", sport="cycling"
        )
        self.assertEqual(event_key("synthetic", run), event_key("synthetic", ride))
        self.assertNotEqual(approval_token("synthetic", run), approval_token("synthetic", ride))

    def test_existing_running_approval_tokens_remain_valid_across_sport_upgrade(self):
        from dataclasses import asdict

        from workoutbridge.publishing import digest

        run = normalize_workout(self.event("Run: 20 min easy"))
        legacy = asdict(run)
        legacy.pop("sport")
        self.assertEqual(
            approval_token("synthetic", run), digest(["synthetic", legacy, event_payload(run)])
        )

    def test_cycling_draft_rejects_running_pace_and_strides(self):
        for text in [
            "4 x 300 m in 90-95 sec with 2 min easy recovery",
            "4 strides with lap recovery",
            "Run 30 min",
        ]:
            with self.subTest(text=text):
                self.assertTrue(parse(text, sport="cycling").unresolved)


class CyclingCliTests(unittest.TestCase):
    def test_stdin_cycling_command_uses_cycling_draft(self):
        import io
        import json
        from unittest.mock import patch

        from workoutbridge.cli import main

        output = io.StringIO()
        with patch("sys.stdin", io.StringIO("Ride 40 min easy")), patch("sys.stdout", output):
            self.assertEqual(main([]), 0)
        self.assertEqual(json.loads(output.getvalue())["sport"], "cycling")
