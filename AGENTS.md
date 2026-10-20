# Contributor Instructions

- Use feature branches and pull requests; do not push directly to main.
- Never commit real athlete data, calendar feeds, credentials, or session tokens.
- Use synthetic fixtures only. Do not copy personal project history here.
- Preserve original prescriptions. Do not invent recovery, pace, or cooldown.
- Unsupported or ambiguous text must require review, never silently disappear.
- Keep parsing, source adapters, and destination adapters separate.
- Live publishing must be opt-in, account-scoped, idempotent, and tested without
  contacting real accounts by default.
- Run `python -m unittest discover -s tests` before submitting changes.
