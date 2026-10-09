# Architecture — Smith Metadata Studio (marcedit-web)

This is the map of how the application is built and the rules that
keep it that way. It describes `origin/main`. When a change alters
anything here, the same ticket updates this file. Decisions with
real trade-offs are recorded as ADRs in `docs/adr/`.

## Purpose

A web application for catalogers to view, validate, edit, transform,
compare, and deduplicate MARC21 records, and to run reusable editing
tasks over batches. It is a Streamlit app in Python 3.9.

## Deployment topology

```
Browser ──► Apache + mod_shib (libtools2.smith.edu/marcedit-web)
              │  strips client identity headers, sets REMOTE_USER / eppn,
              │  adds X-MarcEdit-Proxy-Attestation
              ▼
           Streamlit  127.0.0.1:8501  (systemd: marcedit-web.service)
              │
              ├── SQLite (WAL) + data/ directory
              └── sandbox subprocesses for task execution
```

- **Production** is native Python 3.9 under systemd on Oracle Linux 8.10
  (RHEL-compatible; repo docs say "RHEL 8.10"). No container runtime.
  See `docs/deployment.md`.
- **Deploys** run `scripts/deploy.sh` → `marcedit_web/ops/deploy.py`,
  a lineage-checked deploy that refuses dirty checkouts and branch drift.
- **Docker** is for local development, tests, and verification only.
  `docker-compose.hotfix.yml` mirrors the production topology (web only);
  `docker-compose.yml` is the full durable topology (web + worker).
- **Two run modes** (`lib/runmode.py`, `MARCEDIT_WEB_MODE`):
  - `private` (default; unknown values fail closed to private): signed-in,
    database-backed, full feature set.
  - `public`: read-only tools (Home, View, Validate, Report, Marc Tools),
    no database, no sandbox. These pages are excluded at page
    registration (`App.build_pages`), not hidden at runtime.

## Code layers

```
marcedit_web/
  App.py      entrypoint: page config, navigation, access gate
  views/      page scripts registered by App.py (not auto-discovered)
  render/     Streamlit UI for each workflow
  lib/        deterministic logic, storage, security; testable without Streamlit
  ops/        operational CLIs: health, deploy, backup, maintenance, worker
  schemas/    JSON Schemas and compiler contracts
```

Dependency direction: `views → render → lib`. `ops → lib`.
`lib` never imports `render` or `views`.

- **views/** should be shims (`session.init_page()` then
  `render.<x>.render()`). Known exceptions that hold real logic:
  `6_Diff.py`, `B_Jobs.py`, `00_Home.py`. Do not add more; move logic
  out when those files are next touched under a ticket.
- **lib/** has no module-level Streamlit imports. Known exceptions use
  function-local imports: `session.py`, `identity.py`, `access_gate.py`.
  New lib modules must not import Streamlit at all.

## Navigation (private mode)

Start (Home, Jobs, History, Workspace) · Inspect (View, Find, Validate,
Report) · Edit (Record Editor, Tasks) · Reconcile (Diff, Dedupe,
Marc Tools) · Admin. The Operations page and notifications are behind
`runmode.DURABLE_OPERATIONS_ENABLED` (currently `False`).

## Identity and authorization

- `lib/identity.current_user()`: OAuth email (local dev), then
  `REMOTE_USER`, then `eppn`, then anonymous. Headers are trusted **only**
  when the proxy attestation header matches `MARCEDIT_WEB_PROXY_SECRET`
  (constant-time comparison, fails closed).
- `lib/authz.authorize`: anonymous users are denied; an existing `users`
  row wins; an allowed domain is auto-approved as `cataloger`; anyone
  else becomes `pending`. Roles are `admin` and `cataloger`.
- `lib/access_gate.enforce_access` blocks non-approved users in private mode.
- There are two admin concepts: `users.role = 'admin'` (Admin page) and
  the `MARCEDIT_WEB_ADMINS` env var (raw-Python task Code view).
  Flagged for consolidation.

## Persistence

All runtime state lives under `data/`. Each location can be overridden
with `MARCEDIT_WEB_*_ROOT` / `_PATH` / `_DIR` env vars.

| Store | Module | Notes |
|---|---|---|
| SQLite `data/marcedit.db` | `lib/db.py` | WAL, new connection per call, `foreign_keys=ON`. Hand-written idempotent migrations `_migrate_to_vN`; `SCHEMA_VERSION = 17`. |
| Job files | `lib/job_files.py` | Immutable versions `<file_id>/versions/vNNNNNN.mrc`, plus `exports/` and `pending/`. |
| Uploads | `lib/upload_persistence.py` | Signed-in users only; anonymous uploads are never persisted. |
| Snapshots | `lib/provenance.py` | Before/after provenance. |
| Audit | `lib/audit.py` | Daily JSONL in `data/audit/` plus the `audit_events` table (private mode). |
| Working batch | `lib/record_store.py` | Raw bytes on disk, mmap offsets, lazy pymarc parsing, in-memory override map for edits. |

Schema changes add a new `_migrate_to_vN` and bump `SCHEMA_VERSION`. The
migration must be idempotent and must refuse conflicting existing data
rather than silently rewrite it.

## Collaboration

Job-file work uses one exclusive advisory lock per job file
(`lib/collaboration.acquire_file_checkout`, `lib/locks.py`, TASK-151).
Every mutation compares against the exact version that was opened.
Record and job locks remain only on legacy paths
(`render/single_record_edit.py`). See `docs/adr-collaboration-locking.md`.

## Task model

Tasks are reusable batch transformations. There are three ways to define
them, and all of them execute in the sandbox:

1. **Native tasks** (`lib/native_tasks.py`,
   `schemas/native-task-v1.schema.json`, `docs/native-task-format-v1.md`).
   Non-executable JSON with three actions: `delete_tag`, `build_field`,
   `sort_fields`. Compiled to Python through `task_builder`. The compiled
   body is stored with a compiler fingerprint
   (`native-task-compiler-contract-v1.json`); a fingerprint mismatch
   blocks execution.
2. **Form-built / structured tasks** (`lib/task_builder.py`,
   `lib/task_authoring.py`). Operation palette → generated Python.
   Operations include guided and structural find/replace, RDA,
   partner/institution operations. `lib/operation_reference.py` is the
   canonical cataloger-facing description of each operation.
3. **Legacy raw-Python tasks**: admin-only authoring
   (`MARCEDIT_WEB_ADMINS`).

Supporting pieces:

- **Quick changes** (`lib/quick_field_changes.py`,
  `quick_field_change_runner.py`): one-off edits that are never saved.
  They run through a fixed sandbox adapter and return a candidate; the
  caller decides whether to adopt it.
- **Task library** (`lib/task_library.py`): personal and shared folder
  trees, each with an "Unfiled" root.
- **External MarcEdit task import** (`lib/external_task_*`,
  `schemas/external-task-compatibility-v1.json`,
  `docs/external-task-migration.md`): fail-closed review. Each source
  line keeps its text and a SHA-256. Proven adapters convert to structured
  operations; everything else becomes a blocker for human review.
  `third_party/task-corpora/` is audit input only.
- **Preflight** (`lib/task_preflight.py`): rejects unknown `# OP:` markers
  before compile, submit, or run.

### Execution

- `lib/sandbox.py` runs task code in a **subprocess** with rlimits (CPU,
  memory, file size, process count), a wall-clock timeout, an empty
  environment, and a temporary working directory. A run carries either a
  Python body or an allowlisted structured adapter, never both. This is
  resource isolation, **not** a security sandbox: there is no import
  blocking, chroot, or network namespace. Authorization (who may author
  raw Python) is the security boundary.
- **Current run path:** saved-task runs are synchronous.
  `render/tasks.py` → `lib/synchronous_task_runner.py` → sandbox
  subprocess. The web process spawns the sandbox but never `exec`s task
  code itself.
- **Durable queue** (`lib/operations.py`, `operation_submission.py`,
  `operation_runner.py`, `operation_results.py`, `ops/worker.py`) is
  built but switched off by `DURABLE_OPERATIONS_ENABLED = False`
  (TASK-194 hotfix boundary). Re-enabling it is a roadmap decision,
  not a code tweak.

### AI-assisted drafting

`lib/note_task_draft.py` is a deterministic parser. Gemini
(`lib/gemini_task_draft.py`, only when `GEMINI_API_KEY` is set) is an
optional fallback. `lib/ai_task_draft.py` accepts model output only as
a JSON envelope of palette operations: unsupported kinds and
code-shaped values are rejected, and a human reviews the result in the
form editor. **Model output is never executed or turned into code
directly.**

## Invariants

These must hold. Changing one requires an ADR.

1. Task and user code never runs inside the web process. It runs only in
   `lib/sandbox.py` subprocesses.
2. Task discovery and listing never execute task code (AST parsing only).
3. Model output becomes reviewed palette operations, never code.
4. Literals spliced into generated code go through
   `codegen_safety.lit()` / `data_lit()`. No bare interpolation.
5. Identity headers are trusted only with a valid proxy attestation.
   Identity, run mode, and preflight checks fail closed.
6. Public mode never touches the database or the sandbox, by
   construction.
7. Audit writes never block or raise into the caller.
8. Job-file mutations target the exact version that was opened;
   published versions are immutable.
9. Imported or third-party task content is never silently converted
   into runnable code.
10. `data/marc-rules.txt` is the single source of validation rules and
    help text.
11. Long recursive work never holds the SQLite writer lock.
12. Port 8501 is never exposed beyond loopback. Secrets and `data/` are
    never baked into images.
13. Runtime is Python 3.9. No newer syntax or dependencies.
14. The URL never carries task definitions, MARC data, or OAuth values.

## Known drift (cleanup candidates)

These are flagged, not yet ticketed:

- Repo docs say RHEL 8.10; the host is Oracle Linux 8.10.
- `README.md` links to `docs/application-overview.md`, which is not in
  the repo.
- Stale docstrings: `lib/db.py` ("three tables"), `lib/session.py`
  ("state never persists").
- `lib/run_history.py` is orphaned.
- `render/tasks.py` (about 5,100 lines) and `_submit_queued_run` (unused
  while the queue is off).
- The access-denied screen mentions "Five-College Google login".
- The public systemd unit has no writable paths, so its JSONL audit
  writes fail silently.
- There are two admin concepts (see Identity).

## Testing

- `tests/` is flat; `tests/conftest.py` redirects every data root to
  `tmp_path`.
- CI: `.github/workflows/test.yml` runs `pytest -ra` on Python 3.9.
- Locally, run the suite in Docker (commands in `AGENTS.md`).
  Deploy-file tests run on the host.

## Decision records

- `docs/adr-collaboration-locking.md` — job-file locking (superseded in
  part by TASK-151). New ADRs go in `docs/adr/NNNN-<slug>.md`.
