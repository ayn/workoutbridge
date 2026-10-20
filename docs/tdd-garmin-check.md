# Garmin Read-Only Preflight

Red: `uv run --locked --extra garmin python -m unittest discover -s tests -p
test_garmin_check.py` produced three errors because `garmin-check` did not exist.

Green: after implementing the command, `uv run --locked --extra garmin python -m
unittest discover -s tests` passed all 72 tests.

Coverage verifies destination enumeration and calendar access without mutation,
redaction of authentication exceptions/logs, restoration of logging settings,
and refusal to report success after malformed workout enumeration.

All fixtures are synthetic. No live Garmin authentication, upload, scheduling,
or watch synchronization was performed for this change.
