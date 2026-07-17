# Task 8 Report — Private Operations page

Ticket: [TASK-156](../../.tickets/TASK-156-durable-operation-queue.md)

## Status

Implemented as `224ff095a1adcba77e13d541af6acd670b109828` and hardened
after independent review as `d4ed4ff2a02fa24c124b223aff5f9d0986455f5b`.
TASK-156 remains In-Progress because Tasks 9–11 remain outside this slice.

## Implemented

- Registered `Operations` only in private navigation under Start, using the
  existing `:material/pending_actions:` icon convention, plus a thin page shim
  that initializes the session and shared sidebar.
- Added safe display and action metadata to the existing visible-operation
  read model: source label, artifact-access flag, and current cancel permission.
  Internal artifact paths and task bodies are not exposed by the renderer.
- Added running, queued, needs-attention, and completed metrics; active status
  cards with phase, exact progress, percentage, elapsed time, source,
  submitter, ordered task names, cancellation, and exact worker-unavailable
  messaging.
- Limited the two-second Streamlit fragment to active status. Older Streamlit
  releases retain a manual Material-icon Refresh control.
- Added compact terminal expanders with completion counts, bounded retained
  errors, ordered audit events, timestamps, expiration, and safe summary data.
- Added authorization-preserving Job download/apply/rollback and Quick Load
  download/reopen actions. Artifact bytes are read only after explicit Prepare
  download, and expired bytes are never exposed even before cleanup runs.
- Action errors from operation and Job-file services remain visible without
  speculative local state mutation; successful idempotent actions rerun from
  the durable source of truth.

## Design and accessibility

- Followed a restrained industrial/utilitarian operations-console direction
  within the existing Streamlit design rather than introducing a new theme,
  font, asset, or CSS system.
- Used a predictable hierarchy: counts, live work, then historical detail.
  Bordered active cards and terminal expanders keep dense operational detail
  scannable on wide and narrow layouts.
- Status is always expressed in text, not color alone. Buttons retain explicit
  labels and aligned Material icons. Native Streamlit metrics, progress,
  warnings, expanders, and controls preserve keyboard and contrast behavior.

## TDD evidence

- Initial Docker RED: `11 failed, 4 passed`; failures were the missing private
  route/renderer. A separate read-model RED failed with `KeyError:
  'source_label'`.
- First integrated GREEN: `16 passed` for renderer, navigation, and safe
  read-model metadata.
- Retention-safety RED: a retained-but-expired result was downloadable before
  asynchronous cleanup removed it (`1 failed`).
- Retention-safety GREEN and final focused suite: `93 passed`.

## Verification

- Authoritative focused Docker suite:
  `pytest tests/test_operations_render.py tests/test_app_pages.py
  tests/test_operations.py tests/test_history_render.py tests/test_jobs_page.py -q`
  — `93 passed in 1.66s`, no skips.
- Fresh authoritative full Docker suite after final changes:
  `pytest -q` — `1428 passed, 12 skipped in 33.68s`.
- All 12 skips were explicitly reported existing build-context limitations for
  deployment/docs/Docker source files omitted from the runtime image; no Task 8
  UI, queue, History, or Jobs tests were skipped.
- `git diff --check` passed.
- Post-commit `git status --short` was clean.

## Scoped simplify and self-review

- Reviewed only the Task 8 diff for redundant rendering branches, action
  leakage, unbounded details, path/body exposure, and Python 3.9 compatibility.
- Kept service authorization and deterministic formatting in existing Python
  boundaries; no speculative UI abstraction or theme layer was added.
- Removed a non-established icon argument from the final download control while
  keeping the Material icon on its Prepare action for compatibility with the
  application's supported Streamlit range.
- No blockers or unresolved UI/API contract conflicts remain in this slice.

## Independent review fixes

- Review RED was reproduced in Docker as `7 failed, 44 passed`: active state
  transitions did not refresh full-page counts/history, viewers saw Apply,
  user-controlled task names followed a Markdown render path, ordinary rows
  exposed raw operation internals, and safe action metadata was absent.
- Full-render operation id/state signatures are now retained in session state.
  The active fragment requests one full app rerun when that signature changes,
  covering queued/running/cancelling transitions, active-to-terminal movement,
  and visible operation additions/removals. Progress-only changes remain inside
  the fragment and do not create rerun loops. The established manual Refresh
  fallback remains unchanged.
- `list_visible_operations` now uses explicit SQL and output allowlists. Every
  viewer receives service-derived ordered task names and count-only summaries,
  never task bodies, request JSON, lease tokens, internal paths, or lease
  diagnostics. Approved admins receive only six named operational diagnostic
  fields and still receive no token, body, or path.
- Apply and rollback visibility now requires owner/editor access, completed
  state, required source relationships, and the appropriate current immutable
  Job version. Viewers retain authorized result downloads but receive no Job
  mutation controls; action services continue to recheck every permission and
  checkout at execution time.
- Task names, source labels, and submitter values now use Streamlit plain-text
  rendering so user-controlled text cannot become Markdown or HTML.
- Review-fix focused Docker gate passed: `103 passed in 2.08s`, no skips.
- Fresh review-fix full Docker gate passed: `1438 passed, 12 skipped in 42.05s`.
  The same 12 documented runtime-image build-context skips apply; no Task 8,
  queue, History, or Jobs test was skipped.
- Final `git diff --check` passed and the scoped simplify pass retained exact
  behavior while naming the security allowlists explicitly.
