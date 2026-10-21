"""Private named connections; profiles never contain passwords or feed URLs."""

import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4


def profile_path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Use a short profile name containing letters, numbers, - or _")
    root = Path(
        os.environ.get("WORKOUTBRIDGE_CONFIG_DIR", str(Path.home() / ".config/workoutbridge"))
    ).expanduser()
    if not root.is_absolute() or root.is_symlink() or (root / "profiles").is_symlink():
        raise ValueError("Profile root must be an absolute, non-symlink directory")
    return root / "profiles" / f"{name}.json"


def validate(profile: dict) -> dict:
    if (
        not isinstance(profile, dict)
        or set(profile) != {"version", "destination", "account_id", "session_dir", "state_db"}
        or profile["version"] != 1
        or profile["destination"] not in {"garmin", "coros"}
        or not isinstance(profile["account_id"], str)
        or not re.fullmatch(
            r"[1-9]\d*"
            if profile["destination"] == "garmin"
            else r"coros:(?:us|eu|cn):[^\s]{1,256}",
            profile["account_id"],
        )
    ):
        raise ValueError("Invalid or unsupported connection profile")
    for field in ("session_dir", "state_db"):
        if not isinstance(profile[field], str) or not Path(profile[field]).is_absolute():
            raise ValueError("Profile storage paths must be absolute")
    return profile


def load_profile(name: str) -> dict:
    path = profile_path(name)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_mode & 0o077:
                raise ValueError("Profile file must have private permissions")
            data = handle.read(8193)
        if len(data) > 8192:
            raise ValueError("Profile exceeds size limit")
        return validate(json.loads(data))
    except OSError as exc:
        raise ValueError("Profile is missing or cannot be safely read") from exc


def authenticate_profile(
    name: str,
    session: Path | None = None,
    state_db: Path | None = None,
    *,
    authenticator=None,
    destination="garmin",
) -> dict:
    from .auth import authenticate

    path = profile_path(name)
    root = path.parent.parent
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = load_profile(name) if path.exists() or path.is_symlink() else None
        if destination not in {"garmin", "coros"} or (old and old["destination"] != destination):
            raise ValueError("Cannot change a profile's destination provider")
        if state_db is not None:
            state_db = state_db.expanduser().absolute()
            if old and str(state_db) != old["state_db"]:
                raise ValueError("Cannot replace an existing profile's publishing database")
        session = (
            session.expanduser().absolute()
            if session is not None
            else root / "sessions" / f"{name}-{uuid4().hex}"
        )
        account = (authenticator or authenticate)(session)
        if old and account != old["account_id"]:
            raise ValueError("Reauthentication returned another account; profile unchanged")
        profile = validate(
            {
                "version": 1,
                "destination": destination,
                "account_id": account,
                "session_dir": str(session),
                "state_db": old["state_db"]
                if old
                else str(state_db if state_db is not None else root / "state" / f"{name}.sqlite"),
            }
        )
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".profile-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(profile, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return profile
