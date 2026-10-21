"""One bounded, in-memory Garmin login conversation for the private owner."""

import queue
import re
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from .auth import authenticate
from .profiles import authenticate_profile, profile_path


class GarminLogin:
    def __init__(self, operation, *, timeout=300, config_root=None, claim_account=None, vault=None):
        self.operation = operation
        self.config_root = config_root
        self.claim_account = claim_account
        self.vault = vault
        self.timeout = timeout
        self.lock = threading.RLock()
        self.worker = None
        self.job = {"status": "idle"}
        self.attempts = []
        self.codes = queue.Queue(maxsize=1)
        self.cancelled = threading.Event()

    def status(self):
        with self.lock:
            return dict(self.job)

    def start(self, profile, email, password):
        profile_path(profile, config_root=self.config_root)
        if not isinstance(email, str) or not 3 <= len(email) <= 254 or "@" not in email:
            raise ValueError("Enter a Garmin email")
        if not isinstance(password, str) or not 1 <= len(password) <= 1024:
            raise ValueError("Enter a Garmin password")
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("A Garmin login is already running")
            now = time.monotonic()
            self.attempts = [t for t in self.attempts if t > now - 900]
            if len(self.attempts) >= 3:
                raise ValueError("Wait 15 minutes before trying Garmin login again")
            self.attempts.append(now)
            self.cancelled = threading.Event()
            self.codes = queue.Queue(maxsize=1)
            self.job = {"id": uuid4().hex, "profile": profile, "status": "signing_in"}
            self.worker = threading.Thread(
                target=self._run, args=(profile, email, password, now), daemon=True
            )
            self.worker.start()
            return dict(self.job)

    def _run(self, profile, email, password, started):
        session = None
        saved = False

        def check():
            if self.cancelled.is_set() or time.monotonic() - started >= self.timeout:
                raise ValueError("Login cancelled or expired")

        def prompt():
            check()
            with self.lock:
                self.job["status"] = "mfa"
            code = self.codes.get(timeout=max(0.001, self.timeout - (time.monotonic() - started)))
            check()
            return code

        def login(path):
            nonlocal session
            session = path
            check()
            account = authenticate(path, credentials=(email, password), prompt_mfa=prompt)
            check()
            return account

        acquired = self.operation.acquire(blocking=False)
        try:
            if not acquired:
                raise ValueError("Another operation is running")
            options = (
                {}
                if self.config_root is None
                else {"config_root": self.config_root, "claim_account": self.claim_account}
            )
            if self.vault is not None:
                options["session"] = self.vault.new_path(profile)
            result = authenticate_profile(profile, authenticator=login, **options)
            if self.vault is not None:
                self.vault.save(Path(result["session_dir"]))
            saved = True
            with self.lock:
                self.job.update(status="complete", account=result["account_id"])
        except Exception:  # noqa: BLE001 - never return credentials or provider error details.
            with self.lock:
                self.job.update(
                    status="cancelled" if self.cancelled.is_set() else "failed",
                    error="Garmin sign-in did not complete. Check credentials, code, or account; wait before retrying.",
                )
        finally:
            if acquired:
                self.operation.release()
            if session is not None and not saved:
                shutil.rmtree(session, ignore_errors=True)
            while not self.codes.empty():
                try:
                    self.codes.get_nowait()
                except queue.Empty:
                    break

    def submit(self, job_id, code):
        with self.lock:
            if self.job.get("id") != job_id or self.job["status"] != "mfa":
                raise ValueError("No matching verification request")
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
                raise ValueError("Enter the six-digit verification code")
            self.codes.put_nowait(code)
            self.job["status"] = "signing_in"
            return dict(self.job)

    def cancel(self, job_id):
        with self.lock:
            if self.job.get("id") != job_id:
                raise ValueError("No matching login")
            if self.worker and self.worker.is_alive():
                self.cancelled.set()
                try:
                    self.codes.put_nowait("")
                except queue.Full:
                    pass

    def close(self):
        if self.worker:
            self.cancel(self.job["id"])
            self.worker.join(timeout=1)
