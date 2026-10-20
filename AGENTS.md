# Contributor Instructions

- Use feature branches and pull requests; do not push directly to main.
- Never commit real athlete data, calendar feeds, credentials, or session tokens.
- Use synthetic fixtures only. Do not copy personal project history here.
- Preserve original prescriptions. Do not invent recovery, pace, or cooldown.
- Athlete-approved conversion preferences must be explicit, opt-in policies in
  code, documented in the README, and covered by red/green regression tests.
  Keep the original prescription in destination notes and distinguish added
  steps from coach instructions. Never generalize one athlete's preferences
  into silent defaults for everyone. The documented Final Surge format policy
  defaults unspecified distance-repeat recovery to Lap; preserve explicit
  recovery and provide the `--interval-recovery review` opt-out.
- Unsupported or ambiguous text must require review, never silently disappear.
- Keep parsing, source adapters, and destination adapters separate.
- Live publishing must be opt-in, account-scoped, idempotent, and tested without
  contacting real accounts by default.
- Run `python -m unittest discover -s tests` before submitting changes.
- Red/green TDD is mandatory for every executable behavior change, including
  fixes, UI interactions, adapters, persistence, and deployment tooling:
  write a focused test first, run it and verify the intended failure, implement
  the smallest fix, rerun to green, then refactor with the suite green.
- Record the failing command/reason and passing command/results in the PR.
  Tests written alongside implementation are not evidence of a red phase.
- Documentation-only edits need accuracy/link checks, not artificial tests.
  For infrastructure or external behavior, use contract tests/fakes or a safe
  sandbox; document anything that cannot be verified and do not claim success.
- Publishing must remain disabled until the duplicate-prevention contract in
  `docs/architecture.md` has been implemented and tested.
