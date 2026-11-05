import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workoutbridge.coros import workout_payload
from workoutbridge.coros_publishing import CorosPublisher, approval_token
from workoutbridge.parser import parse
from workoutbridge.publishing import ReviewRequired


class EditableClient:
    account_id = "coros:us:synthetic"

    def __init__(self):
        self.course = None
        self.creates = self.updates = 0
        self.editable = True
        self.lose_response = False
        self.change_id = False
        self.id = "1001"

    def call_tool(self, name, args):
        if name == "queryTrainingSchedule":
            return {"structuredContent": {"workouts": []}}
        if name == "createScheduledWorkout":
            self.creates += 1
            self.course = args["course"]
            return {"structuredContent": {"idInPlan": self.id}}
        if name == "queryScheduledWorkoutDetails":
            if args["idInPlan"] != self.id:
                raise ReviewRequired("Unknown saved identity")
            return {"structuredContent": {"course": self.course, "editable": self.editable}}
        if name == "updateScheduledWorkout":
            self.updates += 1
            self.course = args["course"]
            if self.change_id:
                self.id = "1002"
            if self.lose_response:
                raise TimeoutError("Uncertain update")
            return {"structuredContent": {"idInPlan": self.id}}
        raise AssertionError(name)


class CorosUpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.client = EditableClient()
        self.path = Path(self.folder.name) / "state.sqlite"
        self.publisher = CorosPublisher(self.path, self.client)
        self.course = workout_payload("Synthetic", "Test", parse("run 15 min"))

    def publish(self, course=None, day="2032-03-04"):
        values = dict(source="synthetic", uid="event", day=day, course=course or self.course)
        return self.publisher.publish(
            **values, approved=approval_token(self.client.account_id, **values)
        )

    def receipt(self):
        with sqlite3.connect(self.path) as db:
            return json.loads(db.execute("SELECT record FROM coros_publications").fetchone()[0])

    def changed(self):
        return {
            **self.course,
            "sections": [{"sectionType": 2, "targetType": 2, "targetValue": 1200}],
        }

    def test_updates_existing_identity_and_counts_edit_once(self):
        self.publish()
        self.assertEqual(self.publish(self.changed()), "1001")
        self.assertEqual(self.publish(self.changed()), "1001")
        self.assertEqual((self.client.creates, self.client.updates), (1, 1))
        self.assertEqual(self.receipt()["publication_count"], 2)

    def test_provider_replacement_identity_is_saved_and_verified(self):
        self.publish()
        self.client.change_id = True
        self.assertEqual(self.publish(self.changed()), "1002")
        self.assertEqual(self.publish(self.changed()), "1002")
        self.assertEqual(self.receipt()["id"], "1002")
        self.assertEqual((self.client.creates, self.client.updates), (1, 1))

    def test_lost_update_response_can_verify_without_repeating_write(self):
        self.publish()
        self.client.lose_response = True
        with self.assertRaises(TimeoutError):
            self.publish(self.changed())
        self.client.lose_response = False
        self.publish(self.changed())
        self.assertEqual((self.client.creates, self.client.updates), (1, 1))
        self.assertEqual(self.receipt()["publication_count"], 2)

    def test_rejects_completed_or_moved_workout(self):
        self.publish()
        self.client.editable = False
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed())
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed(), day="2032-03-05")
        self.assertEqual(self.client.updates, 0)

    def test_out_of_band_edits_are_not_overwritten(self):
        self.publish()
        self.client.course = {**self.course, "courseDescription": "Edited outside this publisher"}
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed())
        self.assertEqual(self.client.updates, 0)

    def test_added_target_outside_publisher_is_not_overwritten(self):
        self.publish()
        self.client.course = {
            **self.course,
            "sections": [
                {
                    **self.course["sections"][0],
                    "intensityType": 1,
                    "intensityValueStart": 120,
                    "intensityValueEnd": 140,
                }
            ],
        }
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed())
        self.assertEqual(self.client.updates, 0)

    def test_lost_response_before_update_applies_does_not_repeat_update(self):
        self.publish()
        original = self.client.call_tool

        def failed(name, args):
            if name == "updateScheduledWorkout":
                self.client.updates += 1
                raise TimeoutError("Unknown outcome")
            return original(name, args)

        self.client.call_tool = failed
        with self.assertRaises(TimeoutError):
            self.publish(self.changed())
        self.client.call_tool = original
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed())
        self.assertEqual(self.client.updates, 1)

    def test_legacy_external_title_edit_is_not_hidden_by_title_padding(self):
        self.course["courseName"] = "  Synthetic  "
        self.publish()
        with sqlite3.connect(self.path) as db:
            identity, raw = db.execute("SELECT identity,record FROM coros_publications").fetchone()
            record = json.loads(raw)
            record.pop("course", None)
            db.execute(
                "UPDATE coros_publications SET record=? WHERE identity=?",
                (json.dumps(record), identity),
            )
        self.client.course = {**self.course, "courseName": "An external title edit"}
        with self.assertRaises(ReviewRequired):
            self.publish(self.changed())
        self.assertEqual(self.client.updates, 0)

    def test_legacy_receipt_with_trimmed_title_requires_matching_full_hash(self):
        self.course["courseName"] = "  Synthetic  "
        self.publish()
        with sqlite3.connect(self.path) as db:
            identity, raw = db.execute("SELECT identity,record FROM coros_publications").fetchone()
            record = json.loads(raw)
            record.pop("course", None)
            db.execute(
                "UPDATE coros_publications SET record=? WHERE identity=?",
                (json.dumps(record), identity),
            )
        self.client.course = {**self.course, "courseName": "Synthetic"}
        self.publish(self.changed())
        self.assertEqual(self.client.updates, 1)


if __name__ == "__main__":
    unittest.main()
