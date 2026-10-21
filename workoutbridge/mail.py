"""Transactional verification mail; credentials stay in a private runtime file."""

import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def read_private_secret(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Runtime secret must be a private regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        value = handle.read(4097).strip()
    if not 1 <= len(value) <= 4096:
        raise ValueError("Invalid runtime secret")
    return value


class CloudflareMail:
    def __init__(self, account, token_file, origin):
        if not re.fullmatch(r"[a-f0-9]{32}", account):
            raise ValueError("Invalid Cloudflare account")
        self.account = account
        self.token_file = Path(token_file)
        self.origin = origin
        self.domain = urlsplit(origin).hostname

    def __call__(self, email, link):
        if not link.startswith(self.origin + "/#verify="):
            raise ValueError("Invalid verification origin")
        token = read_private_secret(self.token_file).decode()
        request = Request(
            f"https://api.cloudflare.com/client/v4/accounts/{self.account}/email/sending/send",
            data=json.dumps(
                {
                    "from": f"Prescribed <notifications@{self.domain}>",
                    "to": email,
                    "reply_to": f"support@{self.domain}",
                    "subject": "Verify your email for Prescribed",
                    "text": "Verify your email to create your Prescribed account and register a passkey:\n\n"
                    + link
                    + "\n\nThis link expires in one hour. It is not a sign-in link for an existing account. If you did not request this, ignore this email.",
                }
            ).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                value = json.load(response)
            result = value.get("result") or {}
            if not value.get("success") or not (result.get("queued") or result.get("delivered")):
                raise ValueError("Email not accepted")
        except Exception:  # noqa: BLE001 - never reflect credential-bearing transport errors.
            raise ValueError("Verification email could not be sent") from None
