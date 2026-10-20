# WorkoutBridge

Turn plain-text training prescriptions into reviewable structured workouts.

**Early development, not a hosted service.** Currently a local, dependency-free
draft parser. Calendar import and Garmin publishing are planned, not implemented.
Not affiliated with Garmin, Final Surge, Google, or Apple.

## Try It

Requires Python 3.11 or newer:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
printf '%s\n' 'Warm up until lap; Run 10 min easy; Cool down 5 min' | workoutbridge
python -m unittest discover -s tests -v
```

Output is JSON with the original prescription, normalized steps, unresolved
clauses, and `requires_review: true`. Exit status 2 means unresolved input.
Exit status 0 means parsing succeeded, **not** permission to publish.

The initial grammar accepts semicolon-separated Warm up, Run, Rest, and Cool down
steps with explicit duration/distance or "until lap", plus optional effort labels.
Natural-language intervals, pace ranges, and repeats are intentionally unresolved
until their parsing and validation are implemented. No LLM API is required.

## Intended Workflow

1. Read an authorized calendar feed or manually supplied prescription.
2. Preserve the full title, description, date, and source identity.
3. Convert supported wording into a provider-neutral workout draft.
4. Show ambiguities and require athlete review.
5. Publish structured steps and schedule through a Garmin adapter.
6. Record destination IDs so retries and updates do not create duplicates.

Final Surge write-back is a separate future adapter, contingent on verified
access. Reading its calendar feed does not imply permission or ability to edit
its workouts.

## Safety and Privacy

- Do not invent training, recovery, pace targets, or cooldowns.
- Rep completion times are not pace; conversion must use interval distance.
- Preserve timed easy running as running, not stationary rest.
- Never interpret disappearance from a rolling feed as a deletion request.
- Never commit real calendar files, athlete data, feed URLs, or credentials.
- Examples and tests use synthetic prescriptions only.
- No analytics, account access, network calls, or live writes in this version.

See [architecture and roadmap](docs/architecture.md),
[contributing](CONTRIBUTING.md), and [security](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
