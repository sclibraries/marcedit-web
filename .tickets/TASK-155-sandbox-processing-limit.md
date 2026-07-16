Title: Raise the temporary saved-task sandbox processing limit

Scope:
- Fix the immediate production-testing regression where a legitimate large saved-task run exceeds the sandbox's fixed 30-second wall-clock and CPU limits.
- Raise the temporary default CPU and elapsed-processing limits to 300 seconds through one shared definition.
- Replace cataloger-facing "wall-clock" terminology with plain language describing the maximum processing time.
- Preserve the sandbox's bounded handling of runaway or malicious task code.
- Never allow a timed-out partial output to be applied as a job-file version or downloaded as a completed result.
- Keep this change surgical so it can be tested, reviewed, committed, and deployed independently before the durable queue work in TASK-156.
- Leave merge and split behavior to TASK-157.

Success Criteria:
- A legitimate 60,498-record saved-task run has up to 300 seconds to complete instead of inheriting the fixed 30-second default.
- Parent timeout and parent/child CPU enforcement derive from the same 300-second default and cannot silently drift.
- Tests can inject a shorter processing limit without waiting for the production default.
- Runaway task code still terminates within the configured processing limit.
- A timed-out result says "maximum processing time" rather than "wall-clock," remains visibly failed, and cannot be adopted or downloaded as completed output.
- Automated tests encode why legitimate large work receives the temporary larger budget and why partial output remains unusable.
- Relevant focused and regression test suites pass with no silently skipped checks.
- Code review is complete.

Status: Todo
