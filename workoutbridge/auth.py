"""Interactive Garmin authentication into a new, private session directory."""

import logging
import os
import sys
import warnings
from getpass import GetPassWarning, getpass
from pathlib import Path


def make_client(email, password, *, prompt_mfa):
    from garminconnect import Garmin

    return Garmin(email, password, prompt_mfa=prompt_mfa)


def authenticate(session: Path, *, credentials=None, prompt_mfa=None) -> str:
    if sys.version_info < (3, 12):
        raise ValueError("Garmin authentication requires Python 3.12+")
    session = session.expanduser()
    previous_mask = os.umask(0o077)
    previous_logging = logging.root.manager.disable
    try:
        # A fresh directory prevents silently loading another athlete's existing
        # tokens instead of authenticating the credentials entered here.
        session.mkdir(mode=0o700, parents=True, exist_ok=False)
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            email, password = (
                credentials
                if credentials is not None
                else (input("Garmin email: ").strip(), getpass("Garmin password: "))
            )
            if not email or not password:
                raise ValueError("Credentials required")
            logging.disable(logging.CRITICAL)
            client = make_client(
                email,
                password,
                prompt_mfa=prompt_mfa or (lambda: getpass("Garmin MFA code: ").strip()),
            )
            client.login(tokenstore=str(session))
        token = session / "garmin_tokens.json"
        if type(client.profile_id) is not int or client.profile_id <= 0:
            raise ValueError("Missing stable account identity")
        if token.is_symlink() or not token.is_file() or token.stat().st_size == 0:
            raise ValueError("No saved Garmin session")
        token.chmod(0o600)
        return str(client.profile_id)
    finally:
        logging.disable(previous_logging)
        os.umask(previous_mask)
