import tempfile
import threading
import unittest
from pathlib import Path

from workoutbridge.accounts import Accounts
from workoutbridge.scheduler import Scheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1900000000.0
        self.accounts = Accounts(Path(self.tmp.name), clock=lambda: self.now)
        self.users = [self.accounts.create_user(f"user{i}@example.invalid") for i in range(3)]
        for user in self.users:
            self.accounts.verify_email(user)
            self.accounts.add_credential(user, user, b"public", 0)

    def scheduler(self, run):
        value = Scheduler(self.accounts, run, workers=2)
        self.addCleanup(value.close)
        return value

    def test_distinct_users_run_concurrently_but_capacity_and_claims_are_bounded(self):
        release = threading.Event()
        started = []

        def run(user):
            started.append(user)
            self.assertTrue(release.wait(3))
            return {"checked": 1, "failed": 0}

        scheduler = self.scheduler(run)
        scheduler.tick()
        self.now += 10860
        futures = scheduler.tick()
        try:
            self.assertEqual(len(futures), 2)
            self.assertEqual(scheduler.tick(), [])
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
        self.assertEqual(len(set(started)), 2)
        for future in scheduler.tick():
            future.result(timeout=5)
        self.assertEqual(len(set(started)), 3)

    def test_upgrade_changes_interval_and_restart_blocks_uncertain_inflight_jobs(self):
        scheduler = self.scheduler(lambda _: {"checked": 0, "failed": 0})
        scheduler.tick()
        self.accounts.set_admin(self.users[0], True)
        self.accounts.gift(self.users[0], self.users[1], days=30, reason="Test")
        self.now += 960
        futures = scheduler.tick()
        self.assertEqual(len(futures), 1)
        futures[0].result(timeout=5)
        self.assertEqual(scheduler.status(self.users[1])["interval"], 900)
        with self.accounts.db() as db:
            db.execute("UPDATE schedules SET status='running' WHERE user=?", (self.users[0],))
        scheduler.close()
        restarted = self.scheduler(lambda _: self.fail("Uncertain job retried"))
        self.now += 20000
        self.assertEqual(restarted.status(self.users[0])["status"], "review_required")
        with self.accounts.db() as db:
            db.execute(
                "UPDATE schedules SET next_due=? WHERE user!=?", (self.now + 10000, self.users[0])
            )
        self.assertEqual(restarted.tick(), [])

    def test_failure_is_redacted_and_scheduled_with_backoff_not_a_tight_retry_loop(self):
        scheduler = self.scheduler(lambda _: (_ for _ in ()).throw(ValueError("SECRET")))
        scheduler.tick()
        self.now += 10860
        futures = scheduler.tick()
        for future in futures:
            future.result(timeout=5)
        status = next(
            scheduler.status(user)
            for user in self.users
            if scheduler.status(user)["status"] == "failed"
        )
        self.assertNotIn("SECRET", str(status))
        self.assertGreater(status["next_due"], self.now)
        self.assertIn(status["status"], ("failed", "waiting"))

    def test_frequency_is_plan_enforced_and_downgrade_clamps_without_erasing_preference(self):
        scheduler = self.scheduler(lambda _: {"checked": 0, "failed": 0})
        scheduler.tick()
        user = self.users[0]
        with self.assertRaises(PermissionError):
            scheduler.configure(user, 900)
        scheduler.configure(user, 21600)
        self.assertEqual(scheduler.status(user)["interval"], 21600)
        self.accounts.set_admin(user, True)
        grant = self.accounts.gift(user, user, days=None, reason="Test")
        scheduler.configure(user, 900)
        self.assertEqual(scheduler.status(user)["interval"], 900)
        self.accounts.revoke(user, grant)
        scheduler.tick()
        self.assertEqual(scheduler.status(user)["interval"], 10800)
        self.assertEqual(scheduler.status(user)["requested_interval"], 900)
        with self.assertRaises(ValueError):
            scheduler.configure(user, 1)
