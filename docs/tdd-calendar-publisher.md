# Calendar/Publisher Red-Green Evidence

All fixtures and account IDs are synthetic. No live account calls were made.
Commands below were run from the repository directory.

| Increment | Red observation before implementation | Green |
| --- | --- | --- |
| Calendar import | `python3 -m unittest discover -s tests -p test_calendar.py -v`: missing `workoutbridge.calendar` module | 7 calendar tests passed |
| Intervals/payloads | `uv run --locked python -m unittest discover -s tests -p test_intervals.py -v`: missing Garmin payload module | Full suite: 22 passed |
| Publishing intents | `uv run --locked python -m unittest discover -s tests -p test_publishing.py -v`: missing publishing module | 16 publishing tests passed |
| Deleted schedule regression | Same publishing command: expected ReviewRequired was not raised after editing a workout whose schedule was missing | Fixed preflight guard; suite green |
| Garmin adapter | `uv run --locked python -m unittest discover -s tests -p test_garmin_adapter.py -v`: GarminProvider missing | Full suite: 47 passed |
| CLI workflow | `uv run --locked python -m unittest discover -s tests -p test_workflow.py -v`: six errors because the CLI did not accept command arguments | 6 workflow tests passed |
| Additional safety cases | Full suite: three failures for malformed calendar response, nonfinite interval, and overwrite of a workout without the recorded identity marker | Full suite: 61 passed |
| Independent review regressions | Full suite: three expected failures for pending cross-feed upload overlap, recovery overlooking a foreign scheduled entry, and unknown explicit DTSTART timezone | Full suite: 66 passed |
| Timezone exclusions/identity | Calendar suite: two expected failures for unknown EXDATE and RECURRENCE-ID timezones | Full suite: 68 passed |
| Legacy receipt safety | Publishing suite: expected ReviewRequired was not raised for an older pending receipt lacking overlap metadata | Full suite: 69 passed |

Existing passing tests remained regression coverage. Tests added for already-safe
behavior (process death, pending edits, remote edits) passed on first execution;
they are not presented as red phases or as evidence for a new implementation.

Ruff initially reported import ordering and deliberate broad exception handling.
Imports were mechanically formatted, and redaction/thread-error boundaries were
documented with targeted suppressions. `ruff check` and `ruff format --check`
pass. Wheel and source-distribution builds also succeeded.

## Remaining Verification

- No live Garmin upload, scheduled entry, token refresh, or device sync verified.
- No hosted web UI, remote feed fetcher, multi-host lock, or cloud authentication.
- Parser intentionally rejects unsupported prose rather than partially executing it.
- Read-back tolerates server-added fields and small numeric rounding, but
  unobserved Garmin response changes must fail closed and require investigation.
