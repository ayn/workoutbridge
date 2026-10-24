# Experimental AI interpretations

The optional AI library converts coach text into the existing workout grammar,
then checks that both Garmin and COROS adapters can represent it. Candidates
always retain `requires_review: true`: schema/adapter checks do not prove that
the interpretation preserves every instruction. This tool never publishes,
clears parser review flags or creates publication approvals.

Install the `ai` extra and use your own API key in a mode-600 private regular
file, outside your checkout. No hosted account or subscription is needed.

```python
from pathlib import Path
from workoutbridge.ai import Interpreter, OpenAIClient
from workoutbridge.calendar import Event

interpreter = Interpreter(
    Path("/private/workout-interpretations"),
    OpenAIClient("/private/openai-key"),
    model="gpt-6-luna",  # or gpt-6.1-sol
    monthly_budget="5",
)
event = Event("manual", "example", "", "2030-01-01", "Run", "Jog easily for thirty-five minutes.")
proposal = interpreter.interpret(event)
```

This is library/benchmark tooling, not an AI toggle in the self-hosted web UI.
Existing DIY workflows remain deterministic and do not call OpenAI unless an
operator explicitly uses these tools. Integration into a product's review and
publishing flow requires separate validation and user authorization.

## Compare models

```sh
uv run --locked --extra ai python -m workoutbridge.ai_benchmark \
  --key-file /private/openai-key --data-dir /private/ai-benchmark \
  --models gpt-6-luna gpt-6.1-sol --monthly-budget 5
```

The seed corpus contains 47 hand-specified synthetic cases. Reports distinguish
correct conversions, incorrect candidates, false clearances, correct reviews,
unnecessary reviews and failed requests. Unsupported sports are reported
separately, not credited as model successes. Executable steps and notes are
compared strictly; descriptive source-note matching tolerates capitalization only.
Other semantically equivalent wording may need human adjudication.
This small corpus is not representative launch-quality evidence. Extend it with
checked synthetic fixtures and an independent holdout set; never commit real
athlete data or raw private feeds. A model's confidence score is not acceptance
evidence. Promote validated recurring patterns into deterministic parser rules
through reviewed red/green regression tests.

## Boundaries and storage

Requests contain only sport, workout title and prescription text, with embedded
URL/email redaction. Event identifiers, dates, calendar URLs, connected-service
credentials and device activity history are not request fields. Other personal
details embedded in coaching text may remain. Requests set `store: false`, use
strict Structured Outputs, and have no tools, redirects or automatic retries.
The storage flag is not a claim of zero provider retention.

`ai.sqlite` under the caller-selected root contains redacted inputs and proposals.
Its key includes text, model, schema, prompt and policy version; identical text
can be reused across dates without another request. Different users must use
different cache roots. A hosting application is responsible for authentication,
entitlements, tenant isolation, account deletion and participation controls.

`ai-budget.sqlite` tracks aggregate UTC monthly cost/reservations. By default it
lives in the same root; `budget_root=` allows multiple isolated caches to share
one budget. Cache claims and budget reservations are atomic across processes.
Requests reserve the cost of 32,768 input tokens and a 2,048 output-token maximum,
before contacting the API. Inputs are limited to 8 KB and requests to 24 KB.
Reported usage settles a conservative estimate using input cache-write rates
(1.25 times standard input), without discounts. This is not an invoice or an
account-wide billing guarantee; use OpenAI project controls too. Update configured
rates when pricing changes.

Timeouts, missing usage and process death retain the full reservation. Completed
and failed results remain cached until input/model/policy changes or deliberate
operator eviction. Inspect interrupted `pending` entries before clearing them;
do not erase aggregate budget reservations. `Interpreter.results()` returns
private records for local inspection, never public issue reports.

Sources: [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

The approved recovery policy applies to the AI interpreter too: clearly specified
work with missing or unclear recovery duration uses recovery/rest until Lap.
An identifiable recovery phase with no amount can use `Rest until lap` inside a
cycle; explicit durations, distances and movement remain prescribed. The unclear
source wording stays verbatim in notes. Applying this documented default is not an
unsupported assumption and must not by itself force `unresolved`. Missing work,
contradictory counts, primary alternatives and unsupported targets still require
review. AI candidates remain separate and always require review before publishing.
The shadow-v6 prompt/cache version distinguishes results produced under this policy.
