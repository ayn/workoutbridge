"""Single-host durable scheduling with bounded concurrent athlete jobs."""

import fcntl
import hashlib
import os
import secrets
from concurrent.futures import ThreadPoolExecutor


class Scheduler:
    def __init__(self, accounts, run, *, workers=2, commercial=True):
        self.accounts, self.run = accounts, run
        self.workers, self.commercial = workers, commercial
        self.lock = os.open(
            accounts.database.parent / "scheduler.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(self.lock)
            raise
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="athlete-sync")
        with accounts.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schedules (user TEXT PRIMARY KEY REFERENCES users(id), next_due REAL, interval INTEGER, status TEXT, claim TEXT, started REAL, completed REAL, checked INTEGER DEFAULT 0, failed INTEGER DEFAULT 0)"
            )
            if "requested_interval" not in {
                row[1] for row in db.execute("PRAGMA table_info(schedules)")
            }:
                db.execute("ALTER TABLE schedules ADD COLUMN requested_interval INTEGER")
            # A crashed job may have made remote writes. Never automatically reclaim it.
            db.execute(
                "UPDATE schedules SET status='review_required',claim=NULL WHERE status='running'"
            )

    def _interval(self, db, user):
        minimum = self.accounts._entitlements(db, user)["interval"] if self.commercial else 900
        saved = db.execute(
            "SELECT requested_interval FROM schedules WHERE user=?", (user,)
        ).fetchone()
        return max(minimum, saved[0] or minimum) if saved else minimum

    def configure(self, user, seconds):
        if type(seconds) is not int or seconds not in (900, 1800, 3600, 10800, 21600, 43200, 86400):
            raise ValueError("Choose an available check frequency")
        with self.accounts.db() as db:
            minimum = self.accounts._entitlements(db, user)["interval"] if self.commercial else 900
            if seconds < minimum:
                raise PermissionError("Supporter is required for faster checks")
            db.execute(
                "INSERT OR IGNORE INTO schedules(user,next_due,interval,status) VALUES (?,?,?,'waiting')",
                (user, self.accounts.clock() + seconds, seconds),
            )
            db.execute(
                "UPDATE schedules SET requested_interval=?,interval=?,next_due=? WHERE user=?",
                (seconds, seconds, self.accounts.clock() + seconds, user),
            )

    def tick(self):
        now = self.accounts.clock()
        claims = []
        with self.accounts.db() as db:
            users = db.execute(
                "SELECT id FROM users u WHERE verified=1 AND disabled=0 AND EXISTS(SELECT 1 FROM credentials c WHERE c.user=u.id)"
            ).fetchall()
            for user in users:
                key = user[0]
                interval = self._interval(db, key)
                jitter = int(hashlib.sha256(key.encode()).hexdigest()[:6], 16) % 60
                db.execute(
                    "INSERT OR IGNORE INTO schedules(user,next_due,interval,status) VALUES (?,?,?,'waiting')",
                    (key, now + interval + jitter, interval),
                )
                db.execute(
                    "UPDATE schedules SET next_due=COALESCE(started, next_due-interval)+?,interval=? WHERE user=? AND interval!=? AND status NOT IN ('running','review_required')",
                    (interval, interval, key, interval),
                )
            active = db.execute("SELECT count(*) FROM schedules WHERE status='running'").fetchone()[
                0
            ]
            due = db.execute(
                "SELECT user FROM schedules WHERE next_due<=? AND status NOT IN ('running','review_required') AND user IN (SELECT id FROM users WHERE disabled=0) ORDER BY next_due LIMIT ?",
                (now, max(0, self.workers - active)),
            ).fetchall()
            for row in due:
                claim = secrets.token_hex(16)
                db.execute(
                    "UPDATE schedules SET status='running',claim=?,started=? WHERE user=?",
                    (claim, now, row[0]),
                )
                claims.append((row[0], claim))
        return [self.pool.submit(self._run, user, claim) for user, claim in claims]

    def _run(self, user, claim):
        try:
            result = self.run(user)
            checked, failed = int(result.get("checked", 0)), int(result.get("failed", 0))
        except Exception:  # noqa: BLE001 - jobs must not leak private provider or feed errors.
            checked, failed = 0, 1
        now = self.accounts.clock()
        with self.accounts.db() as db:
            interval = self._interval(db, user)
            db.execute(
                "UPDATE schedules SET status=?,completed=?,next_due=?,interval=?,checked=checked+?,failed=failed+?,claim=NULL WHERE user=? AND claim=?",
                (
                    "failed" if failed else "waiting",
                    now,
                    now + interval,
                    interval,
                    checked,
                    failed,
                    user,
                    claim,
                ),
            )

    def status(self, user):
        with self.accounts.db() as db:
            row = db.execute(
                "SELECT next_due,interval,status,started,completed,checked,failed,requested_interval FROM schedules WHERE user=?",
                (user,),
            ).fetchone()
            return dict(row) if row else None

    def resume(self, user):
        with self.accounts.db() as db:
            db.execute(
                "UPDATE schedules SET status='waiting',next_due=? WHERE user=? AND status='review_required'",
                (self.accounts.clock() + self._interval(db, user), user),
            )

    def close(self):
        if self.lock is not None:
            self.pool.shutdown(wait=True)
            os.close(self.lock)
            self.lock = None
