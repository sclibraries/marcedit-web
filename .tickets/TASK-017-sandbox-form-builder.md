# TASK-017 — Sandbox + form-builder default

**Status:** Completed
**Stage:** 17 (per v3 hardening sequence)

## Title

Close the v2 critical finding: user task code currently runs at full
Streamlit-process privilege via ``tasks.load_user_tasks → exec_module``.
v3 separates the trust model and isolates execution.

## Why

The review surfaced this as the top blocker for Shibboleth production
rollout. Any cataloger could write `import os; os.system("rm -rf /")`
in a task body and the server would happily run it.

## Trust model (decided)

- **Standard users** see only the form builder. The Code view + raw
  Python entry is hidden.
- **Admin users** (eppns listed in `MARCEDIT_WEB_ADMINS` env var) can
  toggle Code view and write raw Python.
- **All user tasks** — admin or not — run in a subprocess sandbox
  with `resource.setrlimit` (CPU, memory, file size, processes),
  a wall-clock timeout, and a cleansed environment. The Streamlit
  process never executes user code directly.

## Scope

- `marcedit_web/lib/sandbox.py` (new):
  * `run_tasks_subprocess(task_bodies: list[str], record_bytes: bytes,
    timeout: float = 30.0) -> SandboxResult` — spawns a child Python
    via ``subprocess.Popen``, applies `resource.setrlimit` from a
    preexec_fn, pipes records in, captures the transformed records
    out, captures stderr for diagnostics.
  * Driver script (inlined or in a sibling file) that reads the
    record stream, applies the task bodies one record at a time,
    writes serialized output back.
  * Resource limits per the platform: CPU (RLIMIT_CPU=30s),
    AS/memory (RLIMIT_AS=512MB), file size (RLIMIT_FSIZE=0 for the
    output is too aggressive — use temp dir + close-after-write
    instead), processes (RLIMIT_NPROC=8).
- `marcedit_web/lib/task_admin.py` (new) — single helper
  `is_admin(user)` reads `MARCEDIT_WEB_ADMINS` (comma-separated
  list) and returns True if the user is in it. Empty allowlist
  means "no admin Code-view at all" (form-only mode). Setting
  ``MARCEDIT_WEB_ADMINS=*`` is the dev escape hatch.
- `marcedit_web/render/tasks.py` rewrite:
  * Hide the "+ New task" Code view button for non-admins. Add a
    "+ New task (form)" button that opens the form builder.
  * For admins, show both: "+ New task (form)" and "+ New task
    (code, admin)" — Code view stays present but explicitly
    labelled.
  * Form builder UI walks `task_builder.OPERATIONS_PALETTE`. For
    each operation in the editor state list, render a small inline
    card with type-specific inputs. "+ Add operation" picks from
    the palette dropdown.
  * On Save, call `task_builder.render_ops_to_python(ops)` to emit
    the body + import lines (which `task_builder` already does
    safely — it builds Python literals via `repr`).
  * Run flow: drop the in-process `for record in records: fn(record)`
    loop. Replace with `sandbox.run_tasks_subprocess(...)` that
    streams records in and out via stdin/stdout.

- `tests/test_sandbox.py` (new):
  * Long-running task: `while True: pass` — sandbox times out at
    the wall clock and returns an error result.
  * Memory bomb: `b" " * (10**10)` — sandbox kills the child via
    RLIMIT_AS without bringing down the parent.
  * Fork bomb: 100 `os.fork()` attempts — RLIMIT_NPROC bounds the
    subprocess tree; parent stays responsive.
  * Filesystem side-effect lands inside the per-run temp workdir,
    not at an attacker-controlled path.

  NOTE — what the sandbox does *not* enforce: there is no
  import-policy or syscall filter, so the child still has working
  ``subprocess``, ``socket``, ``ctypes``, ``open()`` on any path
  the container user can reach. A task that calls
  ``subprocess.run(["/bin/sh", "-c", "true"])`` succeeds. Stage
  21's non-root container + TASK-029's read-only-app-code chown
  bound the blast radius, but capability isolation (seccomp,
  network namespace, restricted-Python) is explicitly *not*
  delivered by this stage. See ``sandbox.py``'s module docstring
  for the live enumeration.

- `tests/test_task_admin.py` (new):
  * `is_admin("user@x")` is False when `MARCEDIT_WEB_ADMINS` unset.
  * `is_admin("user@x")` is True when env has `user@x,other@y`.
  * Wildcard `*` admits everyone.

## Out of scope

- Network namespace isolation (would need rootless podman / nsjail).
  v3 accepts subprocess-level isolation; subsequent stages can
  upgrade.
- Form-builder coverage for every palette operation. Start with the
  generic ops (delete-tag, delete-by-subfield, delete-856-url-contains,
  delete-856-url-regex, sort-fields, set-008-form, add-field,
  build-field, subfield-replace, custom). `custom` is gated to
  admins only.

## Success Criteria

1. With `MARCEDIT_WEB_ADMINS` unset, the Tasks tab shows the form
   builder only — no Code view, no st_ace editor reachable.
2. With `MARCEDIT_WEB_ADMINS=admin@example.edu` and the active
   user being `admin@example.edu`, both form and code paths
   appear.
3. Running a task that calls `os.system(...)` produces a sandbox
   error result and no side effect in the Streamlit container.
4. Running a `while True: pass` task times out at 30s and surfaces
   a timeout error.
5. `docker compose run --rm marcedit-web pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → Tasks → confirm no Code
# view present; create a delete-tag form task; Run; download
# verified.
docker compose down
```

## Verification result (2026-05-24)

- `lib/task_admin.py` (new, ~50 LOC) — env-var allowlist:
  `MARCEDIT_WEB_ADMINS=user@a.edu,user@b.edu` (or `*` for dev).
- `lib/sandbox.py` (new, ~230 LOC) — subprocess runner with
  `resource.setrlimit` (CPU 30s, AS 512MB, FSIZE 1GB, NPROC 32),
  wall-clock `subprocess.run(timeout=...)`, cleansed environment
  (PYTHONPATH/PATH/HOME only). Driver script inline; talks via
  temp files (`input.mrc`, `tasks.json`, `output.mrc`,
  `errors.json`). Records pass through pymarc.MARCReader/Writer
  inside the child. Pre-exposes every public `transforms` helper
  at top level of the per-record namespace so form-emitted bodies
  like `delete_tags(record, "029")` resolve without re-importing.
- `render/tasks.py` rewritten:
  * Form builder is the default editor for all users.
  * Admin Code view (st_ace) appears only when
    `task_admin.is_admin(user)` is True. A clear banner names the
    env var for non-admins.
  * Form editor walks `OPERATIONS_PALETTE`, renders type-aware
    widgets per param (text / bool / indicator / subfield_code /
    select / subfields-as-JSON / code), supports add / reorder /
    remove of ops, round-trips through
    `task_builder.parse_ops_from_source` + `render_ops_to_python`.
  * `custom` (raw-Python) op filtered from the form's add menu for
    non-admins.
  * Save uses an `on_click` callback (avoiding the
    "dictionary changed size during iteration" trap with dynamic
    widget keys).
  * Run path no longer runs in-process — calls
    `sandbox.run_tasks_subprocess(...)` with the parsed task
    bodies. Errors come back as structured per-record entries;
    sandbox timeouts and non-zero exits surface their own banners.
- Tests: 25 new (`test_task_admin.py`: 7 cases covering
  precedence / wildcard / empty user; `test_sandbox.py`: 18 cases
  including noop round-trip, transforms helper resolution,
  task exception captured as structured error, filesystem
  side-effects scoped to the sandbox workdir, wall-clock timeout
  on `while True: pass`, memory bomb against RLIMIT_AS,
  fork-bomb against RLIMIT_NPROC). Total **248 passed in
  3.57s** under Python 3.9-slim.
- Playwright smoke (non-admin user): Home → upload `sample.mrc`
  → Tasks → confirmed banner "you're using the form builder
  path" + no Code view button visible → "+ New task" opened
  the form editor → typed name `delete-029`, description, added
  a `delete-tag` op with tag=029 → Save → file appeared on disk
  at `data/tasks/users/anonymous/delete_029.py` with the
  expected `# OP: delete-tag {"tag": "029"}` marker → Run
  selected tasks → 7 in / 7 out / 0 errors → download
  `sample_20260524_221517.mrc`. Direct in-container subprocess
  call confirmed 029 fields stripped on every record.

All five success criteria satisfied.
