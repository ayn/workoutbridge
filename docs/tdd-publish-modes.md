# Publish Modes TDD

Red: running `uv run --locked --extra garmin python -m unittest discover -s tests
-p test_workflow.py` before implementation produced five errors because the new
flags were not recognized.

Green: the full suite passed 76 tests after implementation.

New coverage includes explicit dry-run without authentication or state creation,
YOLO publishing without hash confirmation, repeated YOLO runs without duplicates,
mutually exclusive modes, and rejection of account mismatch, modified plans,
and unresolved plans under YOLO.

Only synthetic providers were used; no live workouts were changed.
