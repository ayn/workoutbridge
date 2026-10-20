# Native Garmin Authentication

Red: `uv run --locked --extra garmin python -m unittest discover -s tests -p
test_auth.py` failed with six errors before the authentication module existed.

Green: those six tests passed after implementation. Additional coverage checks
that a profile without saved tokens cannot be reported as authenticated.

Tests use synthetic credentials and mock clients. They exercise hidden password
and MFA prompts, private directory/token permissions, umask and logging restoration,
redacted failures, cancellation, and refusal to overwrite existing directories
or follow a destination-directory symlink.

The adapter follows the installed pinned garminconnect 0.3.19 constructor,
prompt_mfa callback, login(tokenstore=...) and garmin_tokens.json conventions.
Authentication tests require Python 3.12+, like the optional Garmin dependency.
No live Garmin login or workout writes were performed.
