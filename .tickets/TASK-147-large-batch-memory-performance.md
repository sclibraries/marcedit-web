Title: Bound memory and accelerate 50K-100K record workflows

Scope:
- Make RecordStore random access independent of record position and avoid
  rebuilding full navigation structures on Streamlit reruns.
- Replace whole-batch bytes and parsed-record collections in View/Edit,
  quick operations, saved tasks, diffs, and snapshots with path-backed,
  streaming artifacts and compact session metadata.
- Add bounded batch concurrency, performance telemetry, and Red Hat
  systemd guardrails for a 2 GB private-service ceiling.
- Preserve synchronous workflows, MARC ordering, rollback snapshots,
  existing task sandboxing, and current user-visible behavior.

Success Criteria:
- Record 100,000 lookup is position-independent and completes in under
  250 ms on the production benchmark host.
- A standard 100K quick operation completes in under 30 seconds without
  retaining whole-batch bytes or parsed records in Streamlit session state.
- Three simultaneous large sessions remain below 1.5 GB cgroup memory with
  no OOM, watchdog restart, skipped records, or silent failures.
- Preview staleness, atomic adoption, snapshot rollback, error cleanup, and
  concurrent batch admission are covered by intent-focused tests.
- The complete test suite passes and code review has no unresolved Critical
  or Important findings.

Status: In-Progress

Implementation Evidence:
- Linux test suite: 1,059 passed, 0 failed, 0 skipped (Python 3.9).
- Synthetic Linux benchmark at 100,000 records: last-record lookup 0.089 ms;
  quick preview plus atomic apply 4.132 s; 100,000 records changed and
  preserved; 76,996,608-byte process peak RSS (51,032,064-byte increase).
- Static verification: all Python sources compile and `git diff --check`
  reports no errors.
- Final self-review found and fixed uncapped sandbox diagnostics, false-success
  telemetry for returned errors, and atomic-adoption temp-file collisions.
  No unresolved Critical or Important code findings remain.

Production Acceptance Remaining:
- Run the documented three-session authenticated smoke test on the RHEL host
  and verify cgroup `MemoryCurrent` stays below 1.5 GB with zero `oom` and
  `oom_kill` events. This cannot be established from the local Linux
  container, so the ticket remains In-Progress until that evidence is added.
