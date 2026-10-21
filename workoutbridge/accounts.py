"""Hosted identities, revocable sessions, and audited non-billing entitlements."""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

MONTH = 30 * 86400


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Accounts:
    def __init__(self, root, *, clock=time.time, plans=True):
        self.clock = clock
        self.plans = plans
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.database = root / "accounts.sqlite"
        fd = os.open(self.database, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0, admin INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, free_provider TEXT, disabled INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(id),
                    public_key BLOB NOT NULL, counter INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(id), expires REAL
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    hash TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(id), expires REAL
                );
                CREATE TABLE IF NOT EXISTS challenges (
                    id TEXT PRIMARY KEY, purpose TEXT, body TEXT, expires REAL
                );
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY, user TEXT REFERENCES users(id), kind TEXT,
                    until REAL, revoked INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, actor TEXT, target TEXT, action TEXT,
                    reason TEXT, at REAL
                );
                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY, user TEXT UNIQUE REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS referrals (
                    invitee TEXT PRIMARY KEY REFERENCES users(id),
                    inviter TEXT REFERENCES users(id), rewarded INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS destinations (
                    provider TEXT, account TEXT, user TEXT REFERENCES users(id),
                    PRIMARY KEY(provider,account)
                );
                CREATE TABLE IF NOT EXISTS throttles (
                    key TEXT PRIMARY KEY, count INTEGER, expires REAL
                );
                CREATE TABLE IF NOT EXISTS billing (
                    user TEXT PRIMARY KEY REFERENCES users(id), customer TEXT UNIQUE,
                    livemode INTEGER NOT NULL, status TEXT DEFAULT 'none',
                    paid_until REAL DEFAULT 0, cancel_pending INTEGER DEFAULT 0,
                    checked REAL DEFAULT 0, checkout_key TEXT, checkout_url TEXT,
                    checkout_expires REAL DEFAULT 0, checkout_plan TEXT
                );
                CREATE TABLE IF NOT EXISTS billing_events (id TEXT PRIMARY KEY, at REAL);
                CREATE TABLE IF NOT EXISTS referral_billing_adjustments (
                    id TEXT PRIMARY KEY REFERENCES grants(id), user TEXT REFERENCES users(id),
                    invitee TEXT REFERENCES users(id), subscription TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', desired_until REAL, created REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_trial_per_user
                    ON grants(user) WHERE kind='trial';
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(billing)")}
            for name, kind in (
                ("subscription", "TEXT"),
                ("plan", "TEXT"),
                ("checkout_trial_end", "REAL"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE billing ADD COLUMN {name} {kind}")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_user(self, email):
        if (
            not isinstance(email, str)
            or not re.fullmatch(r"[^\s@]{1,64}@[^\s@]{1,189}\.[^\s@]+", email)
            or len(email) > 254
        ):
            raise ValueError("Enter a valid email address")
        with self.db() as db:
            # Reuse unverified pending identities without granting access to them.
            old = db.execute(
                "SELECT id FROM users WHERE email=?", (email.strip().lower(),)
            ).fetchone()
            if old:
                return old[0]
            key = uuid4().hex
            db.execute(
                "INSERT INTO users(id,email,created) VALUES (?,?,?)",
                (key, email.strip().lower(), self.clock()),
            )
            return key

    def user(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (key,)).fetchone()
            if row is None:
                raise ValueError("Unknown user")
            return dict(row)

    def verify_email(self, user):
        with self.db() as db:
            db.execute("UPDATE users SET verified=1 WHERE id=?", (user,))

    def add_credential(self, user, credential, public_key, counter, *, initial=False):
        with self.db() as db:
            if initial and db.execute("SELECT 1 FROM credentials WHERE user=?", (user,)).fetchone():
                raise ValueError("Account already has a passkey")
            db.execute(
                "INSERT INTO credentials VALUES (?,?,?,?)", (credential, user, public_key, counter)
            )

    def credential(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM credentials WHERE id=?", (key,)).fetchone()
            return dict(row) if row else None

    def credential_ids(self, user):
        with self.db() as db:
            return [r[0] for r in db.execute("SELECT id FROM credentials WHERE user=?", (user,))]

    def counter(self, key, old, new):
        with self.db() as db:
            if (
                db.execute(
                    "UPDATE credentials SET counter=? WHERE id=? AND counter=?", (new, key, old)
                ).rowcount
                != 1
            ):
                raise ValueError("Concurrent passkey use; try signing in again")

    def email_token(self, user):
        value = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM tokens WHERE user=? OR expires<=?", (user, self.clock()))
            db.execute(
                "INSERT INTO tokens VALUES (?,?,?)", (hashed(value), user, self.clock() + 3600)
            )
        return value

    def consume_email_token(self, token):
        with self.db() as db:
            row = db.execute(
                "SELECT user FROM tokens WHERE hash=? AND expires>?", (hashed(token), self.clock())
            ).fetchone()
            if not row:
                raise ValueError("Verification link expired or already used")
            db.execute("DELETE FROM tokens WHERE hash=?", (hashed(token),))
            db.execute("UPDATE users SET verified=1 WHERE id=?", (row[0],))
            return row[0]

    def new_session(self, user):
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (self.clock(),))
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?)", (hashed(token), user, self.clock() + MONTH)
            )
        return token

    def session_user(self, token):
        with self.db() as db:
            row = db.execute(
                "SELECT s.user FROM sessions s JOIN users u ON s.user=u.id WHERE s.hash=? AND s.expires>? AND u.disabled=0",
                (hashed(token), self.clock()),
            ).fetchone()
            if row:
                return row[0]
        return None

    def renew_session(self, token):
        with self.db() as db:
            return bool(
                db.execute(
                    "UPDATE sessions SET expires=? WHERE hash=? AND expires>?",
                    (self.clock() + MONTH, hashed(token), self.clock()),
                ).rowcount
            )

    def logout(self, token):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (hashed(token),))

    def challenge(self, purpose, body):
        key = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM challenges WHERE expires<=?", (self.clock(),))
            db.execute(
                "INSERT INTO challenges VALUES (?,?,?,?)",
                (hashed(key), purpose, json.dumps(body), self.clock() + 300),
            )
        return key

    def take_challenge(self, key, purpose):
        with self.db() as db:
            row = db.execute(
                "SELECT body FROM challenges WHERE id=? AND purpose=? AND expires>?",
                (hashed(key), purpose, self.clock()),
            ).fetchone()
            if not row:
                raise ValueError("Challenge expired or already used")
            db.execute("DELETE FROM challenges WHERE id=?", (hashed(key),))
            return json.loads(row[0])

    def read_challenge(self, key, purpose):
        with self.db() as db:
            row = db.execute(
                "SELECT body FROM challenges WHERE id=? AND purpose=? AND expires>?",
                (hashed(key), purpose, self.clock()),
            ).fetchone()
            if not row:
                raise ValueError("Enrollment expired")
            return json.loads(row[0])

    def throttle(self, key, *, limit, seconds):
        with self.db() as db:
            db.execute("DELETE FROM throttles WHERE expires<=?", (self.clock(),))
            row = db.execute("SELECT count FROM throttles WHERE key=?", (hashed(key),)).fetchone()
            if row and row[0] >= limit:
                raise PermissionError("Too many requests; try again later")
            db.execute(
                "INSERT INTO throttles VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",
                (hashed(key), self.clock() + seconds),
            )

    def _entitlements(self, db, user):
        if not self.plans:
            return {
                "plan": "self-hosted",
                "interval": 900,
                "until": None,
                "multiple_destinations": True,
                "badges": ["self-hosted"],
            }
        grants = list(
            db.execute(
                "SELECT until,kind FROM grants WHERE user=? AND revoked=0 AND (until IS NULL OR until>?)",
                (user, self.clock()),
            )
        )
        active = [r[0] for r in grants]
        sources = {r[1] for r in grants}
        paid = db.execute(
            "SELECT paid_until,status FROM billing WHERE user=? AND paid_until>?",
            (user, self.clock()),
        ).fetchone()
        if paid:
            active.append(paid[0])
        badges = []
        if paid and paid[1] == "active":
            badges.append("paid")
        if "gift" in sources:
            badges.append("gifted")
        if "trial" in sources or (paid and paid[1] == "trialing"):
            badges.append("trial")
        return {
            "plan": "supporter" if active else "free",
            "interval": 900 if active else 10800,
            "until": (None if None in active else max(active)) if active else None,
            "multiple_destinations": bool(active),
            "badges": badges or (["supporter"] if active else ["free"]),
        }

    def entitlements(self, user):
        with self.db() as db:
            return self._entitlements(db, user)

    def start_trial(self, user):
        if not self.plans:
            return False
        with self.db() as db:
            if not db.execute(
                "SELECT 1 FROM users WHERE id=? AND verified=1 AND disabled=0 AND EXISTS(SELECT 1 FROM credentials WHERE user=users.id)",
                (user,),
            ).fetchone():
                raise PermissionError("Verify email and enroll a passkey first")
            if db.execute("SELECT 1 FROM grants WHERE user=? AND kind='trial'", (user,)).fetchone():
                return False
            self._grant(
                db, "system", user, "trial", 30, "Cardless 30-day trial; no automatic charge"
            )
            return True

    def set_admin(self, user, enabled):
        # Local administrator bootstrap only; never expose this method as a web API.
        with self.db() as db:
            db.execute("UPDATE users SET admin=? WHERE id=?", (int(enabled), user))

    def _admin(self, db, actor):
        if not db.execute(
            "SELECT 1 FROM users WHERE id=? AND admin=1 AND disabled=0", (actor,)
        ).fetchone():
            raise PermissionError("Administrator access required")

    def _grant(self, db, actor, user, kind, days, reason):
        if days is not None and (type(days) is not int or not 1 <= days <= 3650):
            raise ValueError("Choose 1–3650 days or a permanent grant")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
            raise ValueError("Enter a reason")
        current = self._entitlements(db, user)
        until = (
            None
            if days is None
            else max(self.clock(), current["until"] or self.clock()) + days * 86400
        )
        key = uuid4().hex
        db.execute(
            "INSERT INTO grants(id,user,kind,until) VALUES (?,?,?,?)", (key, user, kind, until)
        )
        db.execute(
            "INSERT INTO audit(actor,target,action,reason,at) VALUES (?,?,?,?,?)",
            (actor, user, "grant:" + kind, reason.strip(), self.clock()),
        )
        return key

    def gift(self, actor, user, *, days, reason):
        with self.db() as db:
            self._admin(db, actor)
            return self._grant(db, actor, user, "gift", days, reason)

    def revoke(self, actor, grant):
        with self.db() as db:
            self._admin(db, actor)
            row = db.execute("SELECT user FROM grants WHERE id=?", (grant,)).fetchone()
            if not row:
                raise ValueError("Unknown grant")
            db.execute("UPDATE grants SET revoked=1 WHERE id=?", (grant,))
            db.execute(
                "INSERT INTO audit(actor,target,action,reason,at) VALUES (?,?,?,?,?)",
                (actor, row[0], "revoke", grant, self.clock()),
            )

    def invite(self, user):
        with self.db() as db:
            old = db.execute("SELECT code FROM invites WHERE user=?", (user,)).fetchone()
            if old:
                return old[0]
            key = secrets.token_urlsafe(18)
            db.execute("INSERT INTO invites VALUES (?,?)", (key, user))
            return key

    def _referral_tracker(self, db, user):
        rows = list(
            db.execute(
                """
            SELECT r.rewarded,u.created,u.verified,
                   EXISTS(SELECT 1 FROM referral_billing_adjustments a WHERE a.user=? AND a.invitee=r.invitee AND a.status!='applied') AS billing_pending,
                   EXISTS(SELECT 1 FROM credentials c WHERE c.user=u.id) AS passkey,
                   EXISTS(SELECT 1 FROM destinations d WHERE d.user=u.id) AS connected
            FROM referrals r JOIN users u ON u.id=r.invitee
            WHERE r.inviter=? ORDER BY u.created,r.rowid
        """,
                (user, user),
            )
        )
        earned = sum(bool(r["rewarded"]) for r in rows)
        referrals = []
        for number, row in enumerate(rows, 1):
            state = (
                "reward_pending"
                if row["rewarded"] and row["billing_pending"]
                else "reward_applied"
                if row["rewarded"]
                else "limit_reached"
                if earned >= 3
                else "verify_account"
                if not row["verified"] or not row["passkey"]
                else "connect_destination"
                if not row["connected"]
                else "sync_first_workout"
            )
            referrals.append({"number": number, "joined": row["created"], "status": state})
        return {
            "invited": len(rows),
            "earned_months": earned,
            "remaining": max(0, 3 - earned),
            "cap": 3,
            "referrals": referrals,
        }

    def referral_tracker(self, user):
        with self.db() as db:
            return self._referral_tracker(db, user)

    def accept_invite(self, user, code):
        with self.db() as db:
            row = db.execute("SELECT user FROM invites WHERE code=?", (code,)).fetchone()
            if not row or row[0] == user:
                raise ValueError("Invalid invitation")
            try:
                db.execute("INSERT INTO referrals(invitee,inviter) VALUES (?,?)", (user, row[0]))
            except sqlite3.IntegrityError:
                raise ValueError("Invitation already accepted") from None

    def activate(self, user, *, source, destination, publication):
        # Called only with server-observed state after verified publication, never client flags.
        if not (source and destination and publication):
            return False
        with self.db() as db:
            row = db.execute(
                "SELECT r.inviter FROM referrals r JOIN users u ON u.id=r.invitee WHERE r.invitee=? AND r.rewarded=0 AND u.verified=1 AND u.disabled=0 AND EXISTS(SELECT 1 FROM credentials c WHERE c.user=u.id)",
                (user,),
            ).fetchone()
            if not row:
                return False
            count = db.execute(
                "SELECT count(*) FROM referrals WHERE inviter=? AND rewarded=1", (row[0],)
            ).fetchone()[0]
            if count >= 3:
                return False
            db.execute("UPDATE referrals SET rewarded=1 WHERE invitee=?", (user,))
            for target in (row[0], user):
                grant = self._grant(db, "referral", target, "referral", 30, "Activated invitation")
                billing = db.execute(
                    "SELECT subscription,status FROM billing WHERE user=?", (target,)
                ).fetchone()
                if (
                    billing
                    and billing["subscription"]
                    and billing["status"] not in {"none", "canceled", "incomplete_expired"}
                ):
                    until = db.execute("SELECT until FROM grants WHERE id=?", (grant,)).fetchone()[
                        0
                    ]
                    db.execute(
                        "INSERT INTO referral_billing_adjustments(id,user,invitee,subscription,desired_until,created) VALUES (?,?,?,?,?,?)",
                        (grant, target, user, billing["subscription"], until, self.clock()),
                    )
            return True

    def provider_allowed(self, user, provider):
        current = self.entitlements(user)
        return current["multiple_destinations"] or self.user(user)["free_provider"] in (
            None,
            provider,
        )

    def claim_destination(self, user, provider, account):
        if provider not in {"garmin", "coros"}:
            raise ValueError("Unsupported destination")
        with self.db() as db:
            row = db.execute(
                "SELECT user FROM destinations WHERE provider=? AND account=?", (provider, account)
            ).fetchone()
            if row and row[0] != user:
                raise ValueError("Destination is already connected to another user")
            free = db.execute("SELECT free_provider FROM users WHERE id=?", (user,)).fetchone()[0]
            if not self._entitlements(db, user)["multiple_destinations"] and free not in (
                None,
                provider,
            ):
                raise PermissionError("Supporter is required for multiple destination services")
            db.execute(
                "INSERT OR IGNORE INTO destinations VALUES (?,?,?)", (provider, account, user)
            )
            if free is None:
                db.execute("UPDATE users SET free_provider=? WHERE id=?", (provider, user))

    def choose_provider(self, user, provider):
        with self.db() as db:
            if not db.execute(
                "SELECT 1 FROM destinations WHERE user=? AND provider=?", (user, provider)
            ).fetchone():
                raise ValueError("Choose a connected destination service")
            db.execute("UPDATE users SET free_provider=? WHERE id=?", (provider, user))

    def admin_users(self, actor):
        with self.db() as db:
            self._admin(db, actor)
            users = []
            for row in db.execute(
                "SELECT id,email,verified,admin,created,disabled FROM users ORDER BY created DESC LIMIT 1000"
            ):
                value = dict(row)
                value["entitlements"] = self._entitlements(db, row["id"])
                value["referrals"] = self._referral_tracker(db, row["id"])
                billing = db.execute(
                    "SELECT status,plan,paid_until,cancel_pending,checked FROM billing WHERE user=?",
                    (row["id"],),
                ).fetchone()
                value["billing"] = dict(billing) if billing else None
                value["destinations"] = db.execute(
                    "SELECT count(*) FROM destinations WHERE user=?", (row["id"],)
                ).fetchone()[0]
                users.append(value)
            return {
                "users": users,
                "billing_adjustments": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,user,status,desired_until,created FROM referral_billing_adjustments ORDER BY created DESC LIMIT 1000"
                    )
                ],
                "grants": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,user,kind,until,revoked FROM grants ORDER BY rowid DESC LIMIT 1000"
                    )
                ],
                "audit": [
                    dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")
                ],
            }

    def audit_view(self, actor):
        with self.db() as db:
            self._admin(db, actor)
            db.execute(
                "INSERT INTO audit(actor,target,action,reason,at) VALUES (?,?,?,?,?)",
                (actor, "users", "admin_view", "Viewed administrative overview", self.clock()),
            )
