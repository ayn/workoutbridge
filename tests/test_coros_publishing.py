import json
import tempfile
import unittest
from pathlib import Path

from workoutbridge.coros import workout_payload
from workoutbridge.coros_publishing import CorosPublisher, approval_token
from workoutbridge.parser import parse
from workoutbridge.publishing import ReviewRequired


class FakeClient:
    account_id = "coros:us:synthetic"

    def __init__(self):
        self.writes = 0
        self.course = None
        self.timeout = False
        self.mismatch = False

    def call_tool(self, name, arguments):
        if name == "queryTrainingSchedule":
            return {"structuredContent": {"workouts": []}}
        if name == "createScheduledWorkout":
            self.writes += 1
            self.course = arguments["course"]
            if self.timeout:
                raise ValueError("Uncertain write")
            return {"structuredContent": {"idInPlan": "9223372036854775806"}}
        if name == "queryScheduledWorkoutDetails":
            return {"structuredContent": {"course": {} if self.mismatch else self.course}}
        raise AssertionError(name)


class CorosPublishingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeClient()
        self.publisher = CorosPublisher(Path(self.directory.name) / "state.sqlite", self.client)
        self.course = workout_payload("Synthetic", "Integration test", parse("run 10 min"))
        self.day = "2026-10-22"

    def publish(self, **kwargs):
        values = {"source": "test", "uid": "one", "day": self.day, "course": self.course}
        values.update(kwargs)
        token = approval_token(self.client.account_id, **values)
        return self.publisher.publish(**values, approved=token)

    def test_create_verify_and_repeat_does_not_duplicate(self):
        self.assertEqual(self.publish(), "9223372036854775806")
        self.assertEqual(self.publish(), "9223372036854775806")
        self.assertEqual(self.client.writes, 1)

    def test_timeout_latches_pending_intent(self):
        self.client.timeout = True
        with self.assertRaises(ValueError):
            self.publish()
        self.client.timeout = False
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.client.writes, 1)

    def test_readback_failure_never_creates_again(self):
        self.client.mismatch = True
        with self.assertRaises(ReviewRequired):
            self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.client.writes, 1)

    def test_moved_or_edited_events_require_review(self):
        self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish(day="2026-10-23")
        changed = {**self.course, "courseName": "Changed"}
        with self.assertRaises(ReviewRequired):
            self.publish(course=changed)
        self.assertEqual(self.client.writes, 1)

    def test_wrong_approval_does_not_write(self):
        with self.assertRaises(ReviewRequired):
            self.publisher.publish(
                source="test", uid="one", day=self.day, course=self.course, approved="wrong"
            )
        self.assertEqual(self.client.writes, 0)

    def test_overlapping_sources_blocked(self):
        self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish(source="another")
        self.assertEqual(self.client.writes, 1)

    def test_unknown_calendar_shape_blocks_creation(self):
        self.client.call_tool = lambda name, arguments: {
            "content": [{"type": "text", "text": "Unexpected format"}]
        }
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.client.writes, 0)

    def test_encoded_text_confirmation_and_inline_course_json(self):
        original = self.client.call_tool

        def text_result(name, arguments):
            original(name, arguments)
            if name == "createScheduledWorkout":
                text = "Workout created on 20261022: Synthetic (Running).\nidInPlan: 9223372036854775806\nTo change this workout later, use the app."
            elif name == "queryScheduledWorkoutDetails":
                text = (
                    "Scheduled Workout Detail\n========================\nDate: 2026-10-22\nidInPlan: 9223372036854775806\nName: Synthetic\nEditable via MCP: yes\nCourse JSON: "
                    + json.dumps(self.course)
                    + "\n\nUpdate hint: copy the course."
                )
            else:
                text = "No training schedule found."
            return {"content": [{"type": "text", "text": json.dumps(text)}]}

        self.client.call_tool = text_result
        self.assertEqual(self.publish(), "9223372036854775806")
        self.publish()
        self.assertEqual(self.client.writes, 1)

    def test_explicit_reconcile_verifies_pending_write_without_creation(self):
        self.client.timeout = True
        with self.assertRaises(ValueError):
            self.publish()
        values = dict(source="test", uid="one", day=self.day, course=self.course)
        self.publisher.reconcile(
            **values,
            remote_id="9223372036854775806",
            approved=approval_token(self.client.account_id, **values),
        )
        self.client.timeout = False
        self.publish()
        self.assertEqual(self.client.writes, 1)

    def test_reconcile_mismatch_remains_pending(self):
        self.client.timeout = True
        with self.assertRaises(ValueError):
            self.publish()
        self.client.mismatch = True
        values = dict(source="test", uid="one", day=self.day, course=self.course)
        with self.assertRaises(ReviewRequired):
            self.publisher.reconcile(
                **values, remote_id="123", approved=approval_token(self.client.account_id, **values)
            )
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.client.writes, 1)
