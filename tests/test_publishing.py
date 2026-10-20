import json
import sqlite3
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event as Signal
from threading import Thread

from workoutbridge.calendar import Event
from workoutbridge.publishing import Publisher, ReviewRequired, approval_token


class FakeGarmin:
    account_id = "synthetic-athlete"

    def __init__(self):
        self.workouts = {}
        self.calendar = []
        self.uploads = self.updates = self.schedules = 0
        self.fail_upload = self.fail_schedule = self.fail_update = False
        self.entered = self.release = None

    def list_workouts(self):
        return list(deepcopy(self.workouts).values())

    def get_workout(self, wid):
        return deepcopy(self.workouts[wid])

    def upload(self, payload):
        self.uploads += 1
        if self.entered:
            self.entered.set()
            self.release.wait(5)
        wid = str(self.uploads)
        self.workouts[wid] = {**deepcopy(payload), "workoutId": wid}
        if self.fail_upload:
            raise TimeoutError("synthetic upload response lost")
        return wid

    def update(self, wid, payload):
        self.updates += 1
        self.workouts[wid] = {**deepcopy(payload), "workoutId": wid}
        if self.fail_update:
            raise TimeoutError("synthetic update response lost")

    def list_schedule(self, day):
        return [deepcopy(e) for e in self.calendar if e["date"] == day]

    def schedule(self, wid, day):
        self.schedules += 1
        self.calendar.append({"workoutId": wid, "date": day})
        if self.fail_schedule:
            raise TimeoutError("synthetic schedule response lost")


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "state.sqlite"
        self.provider = FakeGarmin()
        self.event = Event("feed-a", "event-a", "", "2027-01-05", "Easy", "Run 15 min")

    def publish(self, event=None, provider=None, token=None):
        event = event or self.event
        provider = provider or self.provider
        return Publisher(self.db, provider).publish(
            event,
            token or approval_token(provider.account_id, event),
        )

    def test_repeat_and_restart_are_noops(self):
        self.publish()
        self.publish()
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_explicit_approval_required_and_bound_to_content(self):
        token = approval_token(self.provider.account_id, self.event)
        for event, approval in (
            (self.event, "not-approved"),
            (replace(self.event, description="Run 20 min"), token),
        ):
            with self.assertRaises(ReviewRequired):
                self.publish(event, token=approval)
        self.assertEqual(self.provider.uploads, 0)

    def test_changed_workout_updates_existing_id(self):
        self.publish()
        self.publish(replace(self.event, description="Run 20 min"))
        self.assertEqual(
            (self.provider.uploads, self.provider.updates, self.provider.schedules), (1, 1, 1)
        )

    def test_moved_event_requires_manual_reconciliation(self):
        self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, date="2027-01-06"))
        self.assertEqual(self.provider.schedules, 1)

    def test_cancelled_and_unknown_text_never_publish(self):
        for event in (
            replace(self.event, cancelled=True),
            replace(self.event, description="Run 15 min; unspecified intervals"),
        ):
            with self.assertRaises(ValueError):
                self.publish(event)
        self.assertEqual(self.provider.uploads, 0)

    def test_upload_response_loss_recovers_by_marker_without_recreating(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.fail_upload = False
        self.publish()
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))

    def test_uncertain_upload_absent_remotely_blocks_retry(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.workouts.clear()
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.uploads, 1)

    def test_schedule_response_loss_does_not_schedule_twice(self):
        self.provider.fail_schedule = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.fail_schedule = False
        self.publish()
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))

    def test_uncertain_schedule_blocks_retry_if_absent(self):
        self.provider.fail_schedule = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.calendar.clear()
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.schedules, 1)

    def test_update_response_loss_recovers_without_repeating_update(self):
        self.publish()
        self.provider.fail_update = True
        changed = replace(self.event, description="Run 20 min")
        with self.assertRaises(TimeoutError):
            self.publish(changed)
        self.provider.fail_update = False
        self.publish(changed)
        self.assertEqual(self.provider.updates, 1)

    def test_edit_does_not_recreate_a_missing_schedule(self):
        self.publish()
        self.provider.calendar.clear()
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, description="Run 20 min"))
        self.assertEqual(self.provider.schedules, 1)

    def test_ambiguous_upload_markers_block(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.workouts["other"] = {
            **deepcopy(self.provider.workouts["1"]),
            "workoutId": "other",
        }
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.uploads, 1)

    def test_process_death_after_upload_is_reconciled(self):
        upload = self.provider.upload

        def crash(payload):
            upload(payload)
            raise SystemExit("simulated process death")

        self.provider.upload = crash
        with self.assertRaises(SystemExit):
            self.publish()
        self.provider.upload = upload
        self.publish()
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))

    def test_unknown_update_outcome_does_not_repeat_the_update(self):
        self.publish()
        original = deepcopy(self.provider.workouts["1"])
        self.provider.fail_update = True
        changed = replace(self.event, description="Run 20 min")
        with self.assertRaises(TimeoutError):
            self.publish(changed)
        self.provider.workouts["1"] = original
        with self.assertRaises(ReviewRequired):
            self.publish(changed)
        self.assertEqual(self.provider.updates, 1)

    def test_changed_pending_intent_requires_reconciliation(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, description="Run 20 min"))
        self.assertEqual(self.provider.uploads, 1)

    def test_remote_edit_is_not_overwritten_without_new_approval(self):
        self.publish()
        self.provider.workouts["1"]["workoutName"] = "Edited elsewhere"
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.updates, 0)

    def test_disappeared_feed_event_does_not_delete_destination(self):
        self.publish()
        # An empty subsequent poll makes no calls; there is no implicit delete operation.
        for event in []:
            self.publish(event)
        self.assertEqual(len(self.provider.workouts), 1)
        self.assertEqual(len(self.provider.calendar), 1)

    def test_foreign_workout_cannot_replace_recorded_id(self):
        self.publish()
        self.provider.workouts["1"]["description"] = "Unrelated workout"
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, description="Run 20 min"))
        self.assertEqual(self.provider.updates, 0)

    def test_account_isolation(self):
        self.publish()
        other = FakeGarmin()
        other.account_id = "another-synthetic-athlete"
        self.publish(provider=other)
        self.assertEqual(other.uploads, 1)

    def test_recurring_instances_are_distinct(self):
        self.publish(replace(self.event, recurrence_id="2027-01-05"))
        self.publish(replace(self.event, recurrence_id="2027-01-12", date="2027-01-12"))
        self.assertEqual(self.provider.uploads, 2)

    def test_cross_feed_overlap_blocks_not_silently_merged(self):
        self.publish()
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, source="another-feed"))
        self.assertEqual(self.provider.uploads, 1)

    def test_pending_upload_blocks_equivalent_second_feed(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.fail_upload = False
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, source="second-feed"))
        self.publish()
        self.assertEqual((self.provider.uploads, self.provider.schedules), (1, 1))

    def test_legacy_receipt_requires_migration_not_duplicate_creation(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        with sqlite3.connect(self.db) as db:
            key, stored = db.execute("SELECT identity, record FROM publications").fetchone()
            record = json.loads(stored)
            for field in ("account_id", "title_key", "steps_hash"):
                del record[field]
            db.execute(
                "UPDATE publications SET record=? WHERE identity=?", (json.dumps(record), key)
            )
        self.provider.fail_upload = False
        with self.assertRaises(ReviewRequired):
            self.publish(replace(self.event, source="second-feed"))
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.uploads, 1)

    def test_recovered_upload_rechecks_foreign_calendar_overlap(self):
        self.provider.fail_upload = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.provider.fail_upload = False
        self.provider.workouts["outside"] = {
            **deepcopy(self.provider.workouts["1"]),
            "workoutId": "outside",
            "description": "Created independently",
        }
        self.provider.calendar.append({"workoutId": "outside", "date": self.event.date})
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.schedules, 0)

    def test_preexisting_calendar_workout_blocks(self):
        self.provider.workouts["existing"] = {"workoutName": "Easy", "workoutId": "existing"}
        self.provider.calendar.append({"workoutId": "existing", "date": self.event.date})
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.uploads, 0)

    def test_duplicate_remote_calendar_entries_block(self):
        self.publish()
        self.provider.calendar.append(deepcopy(self.provider.calendar[0]))
        with self.assertRaises(ReviewRequired):
            self.publish()
        self.assertEqual(self.provider.schedules, 1)

    def test_concurrent_process_claim_blocks_second_writer(self):
        self.provider.entered, self.provider.release = Signal(), Signal()
        errors = []

        def first():
            try:
                self.publish()
            except Exception as exc:  # noqa: BLE001 - propagate worker failures to the test.
                errors.append(exc)

        thread = Thread(target=first)
        thread.start()
        try:
            self.assertTrue(self.provider.entered.wait(3))
            with self.assertRaises(ReviewRequired):
                self.publish()
        finally:
            self.provider.release.set()
            thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(self.provider.uploads, 1)
