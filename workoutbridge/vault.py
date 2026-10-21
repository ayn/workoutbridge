"""Encrypt provider session directories; plaintext lives only in tenant-scoped tmpfs."""

import base64
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken


class SessionVault:
    def __init__(self, sealed, runtime, key):
        self.sealed, self.runtime = Path(sealed), Path(runtime)
        self.cipher = Fernet(key)
        for folder in (self.sealed, self.runtime):
            if folder.is_symlink():
                raise ValueError("Session root must not be a symlink")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            folder.chmod(0o700)

    def new_path(self, label):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", label):
            raise ValueError("Invalid session label")
        return self.runtime / (label + "-" + uuid4().hex)

    def _path(self, session):
        session = Path(session)
        if (
            session.parent != self.runtime
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", session.name)
            or session.is_symlink()
        ):
            raise ValueError("Session belongs to another tenant")
        return session, self.sealed / (session.name + ".sealed")

    def save(self, session):
        session, target = self._path(session)
        if not session.is_dir():
            raise ValueError("Provider session is missing")
        files, size = {}, 0
        for path in session.rglob("*"):
            if path.is_symlink():
                raise ValueError("Unsafe session file")
            if path.is_file():
                data = path.read_bytes()
                size += len(data)
                if size > 4 * 1024 * 1024 or len(files) >= 100:
                    raise ValueError("Session exceeds size limit")
                files[path.relative_to(session).as_posix()] = base64.b64encode(data).decode()
        encrypted = self.cipher.encrypt(json.dumps(files).encode())
        fd, name = tempfile.mkstemp(dir=self.sealed, prefix=".vault-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    def restore(self, session):
        session, target = self._path(session)
        if session.is_dir():
            return
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Saved provider session is unavailable")
        try:
            files = json.loads(self.cipher.decrypt(target.read_bytes()))
        except (InvalidToken, ValueError):
            raise ValueError("Saved provider session cannot be decrypted") from None
        if not isinstance(files, dict) or len(files) > 100:
            raise ValueError("Invalid saved session")
        decoded = {}
        size = 0
        for name, value in files.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Unsafe saved session path")
            decoded[name] = base64.b64decode(value, validate=True)
            size += len(decoded[name])
        if size > 4 * 1024 * 1024:
            raise ValueError("Session exceeds size limit")
        session.mkdir(mode=0o700)
        for name, value in decoded.items():
            path = session / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(value)
