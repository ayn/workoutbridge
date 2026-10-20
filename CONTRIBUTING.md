# Contributing

Use feature branches and pull requests. Run:

```sh
python -m unittest discover -s tests -v
```

Include synthetic fixtures for parser changes, especially ambiguous instructions.
Do not submit real calendar exports, credentials, or identifiable training logs.
Keep unsupported wording visible and require review rather than guessing.
Discuss new provider integrations before adding dependencies or network access.

## Required Red/Green TDD

For every behavior change:

1. Write a focused failing test before production code.
2. Run it and confirm it fails for the intended missing behavior, not an unrelated
   setup problem.
3. Implement the smallest change that makes it pass.
4. Run the focused tests and full relevant suite.
5. Refactor only while keeping the tests green.

Apply this to parsing, publishing, concurrency, UI interactions, authentication,
and deployment tooling. Use fake providers and deterministic clocks; live
accounts must not be necessary for the normal suite.

PRs must include red and green commands/results, plus remaining verification
gaps. CI proves the final suite passes; it does not prove tests were written
first. Documentation-only changes are exempt from red/green execution but
still need review for accuracy.

The initial parser was introduced with tests, without a recorded red phase.
Do not retroactively describe that initial implementation as red/green TDD.
