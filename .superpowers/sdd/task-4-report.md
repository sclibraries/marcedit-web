# TASK-156 Task 4 Report — Cancellable sandbox progress

Ticket: [TASK-156](../../.tickets/TASK-156-durable-operation-queue.md)

## Status

Completed. `run_tasks_subprocess` remains backward compatible while adding an
atomic progress sidecar, deduplicated progress callback, cancellation callback,
bounded polling, and a distinct `SandboxResult.cancelled` outcome. The sandbox
now launches in a new POSIX session and terminates the entire owned process
group with SIGTERM, a bounded two-second grace, SIGKILL, and one final reap.

## Files

- `marcedit_web/lib/sandbox.py`
- `tests/test_sandbox.py`
- `.superpowers/sdd/task-4-report.md`

No queue lifecycle, runner, worker, UI, result-publishing, or deployment files
were changed.

## TDD evidence

All meaningful test commands used the supported Docker service and existing
`marcedit-web` Compose project/network:

```text
docker compose --project-name marcedit-web run --rm --no-deps marcedit-web pytest <paths> -q
```

### Initial RED

`tests/test_sandbox.py`: **2 failed, 23 passed in 4.27s**. The two intended
failures were `TypeError` for the missing `progress_path` and
`cancel_requested` keyword arguments. Production code was unchanged at this
point.

### Core GREEN

After adding child progress writes, parent polling, `Popen`, and cancellation,
the required sandbox behaviors passed. Legacy tests that mocked
`subprocess.run` were updated to exercise the new `Popen` boundary while
retaining their CPU-limit, elapsed-timeout, SIGXCPU, and ordinary nonzero-exit
assertions.

Additional RED/GREEN cycles proved edge behavior rather than relying on code
inspection:

- callback cleanup RED: the callback exception propagated but sent no signal
  and did not reap the child; GREEN terminates and reaps before reraising;
- process-exit race RED: `ProcessLookupError` escaped from `killpg`; GREEN
  treats the disappeared group as completion and reaps the leader;
- cancellation/SIGXCPU RED: one result was both cancelled and timed out;
  GREEN makes observed cancellation win classification;
- independent-review RED: **3 failed** for completion losing to cancellation,
  stale reused-workdir artifacts, and inherited stdout/stderr pipes;
- descendant teardown RED: SIGTERM was sent but SIGKILL was omitted when the
  leader accepted TERM while a descendant could ignore it; GREEN holds the
  leader unreaped through the grace/KILL attempt and then communicates once.

Final focused sandbox result: **33 passed in 8.54s**.

## Signal, cancellation, and progress evidence

- `start_new_session=True` creates a new process group for every sandbox.
- Cancellation and elapsed timeout use the same group teardown path.
- Teardown sends SIGTERM, waits exactly the bounded two-second grace while the
  unreaped leader prevents PID/PGID reuse, attempts SIGKILL for any surviving
  group member, then performs a single final `communicate()` reap.
- Tests cover TERM-resistant leaders, leaders exiting while descendants may
  survive, a group disappearing between observation and signal, and callback
  failure racing with leader exit.
- Child stderr is redirected to a disk-backed file. Descendants cannot keep a
  parent-owned capture pipe open, and stderr remains available for existing
  error normalization.
- Cancellation is neither a timeout nor an ordinary nonzero failure, including
  a concurrent SIGXCPU return.
- Progress JSON is written to a temporary sibling and atomically replaced.
  Parent polling ignores invalid/partial JSON and reports each changed integer
  value only once. Final progress is read after child completion.
- Reused workdirs clear prior output, errors, stderr, and progress before
  launch, preventing stale results on early cancellation.

## Compatibility and full verification

Required compatibility command:

```text
pytest tests/test_sandbox.py tests/test_tasks_export.py tests/test_batch_replace.py tests/test_codegen_safety.py -q
```

Final result: **120 passed in 12.54s**.

Final full-suite command:

```text
pytest -q
```

Final result after the simplify pass: **1331 passed, 12 skipped in 33.66s**.
The 12 skips were reported by pytest and are not claimed as coverage:

- 7 deployment-unit cases whose service/docs files are absent from the built
  image context;
- 5 Docker configuration cases whose `.dockerignore`/`Dockerfile` files are
  absent from the built image context.

`python3 -m py_compile marcedit_web/lib/sandbox.py tests/test_sandbox.py` and
`git diff --check` both passed.

## Self-review and independent review

Self-review found and fixed cancellation/SIGXCPU double classification,
callback-exception cleanup, and the `killpg` exit race. Independent review then
identified three boundary issues: inherited-pipe hangs/descendant survival,
completion misclassification, and stale artifacts in reused workdirs. Each was
given a regression and fixed. A second review found that leader-based TERM
completion could still leave a TERM-ignoring descendant; teardown was revised
to retain the unreaped process-group identity through grace and KILL. Final
independent re-review reported no remaining Critical or Important findings.

## Concerns and constraints

- This boundary remains POSIX-specific and retains the existing POSIX pytest
  guard. Supported verification ran in the Linux/Python 3.9 Docker service.
- Cancellation/elapsed-timeout teardown can intentionally take the full
  two-second grace before KILL. This is the specified bound and is required to
  give cooperative group members time to exit while still guaranteeing
  descendant cleanup.
- The sandbox remains a resource-limited subprocess boundary, not a complete
  security sandbox; the existing module-level limitations remain unchanged.

## Controller-review follow-up

An independent controller rejected the first Task 4 commit because progress was
reported before checking cancellation and was reported again unconditionally
after cancellation teardown. Future queue progress callbacks renew the lease;
once the operation enters `cancelling`, that callback must not run. The
controller also found that startup removed `progress.json` but not the fixed
atomic-write sibling `progress.json.tmp`.

Strict follow-up RED command:

```text
pytest tests/test_sandbox.py::test_cancellation_preempts_progress_callbacks tests/test_sandbox.py::test_startup_removes_stale_progress_temporary -q
```

Result: **2 failed** for the intended reasons. The cancellation test raised
`RuntimeError: lease entered cancelling state` from the unconditional final
progress callback after teardown advanced the sidecar. The temporary cleanup
test found the stale `.tmp` sibling still present.

The surgical fix makes each poll order completion, cancellation, then progress;
it skips the final progress callback only for a cancelled result and removes the
fixed `.tmp` sibling at startup. Successful non-cancelled completion retains its
final progress read.

Focused GREEN evidence:

- targeted cancellation/temporary/success-final-progress tests: **3 passed in
  0.18s**;
- complete sandbox suite: **35 passed in 6.31s**;
- required compatibility set: **122 passed in 9.95s**;
- final full Docker suite: **1333 passed, 12 skipped in 30.76s**.

The same 12 build-context skips listed above were explicitly reported. No skip
is claimed as coverage.
