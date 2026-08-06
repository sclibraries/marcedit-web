# Visible Operation Progress Design

**Ticket:** [TASK-197](../../../.tickets/TASK-197-visible-operation-progress.md)

## Goal

Make long-running MARC operations visibly active in the page. The cataloger
should see what the application is doing, how far it has progressed when the
engine provides record counts, and a readable final state when the operation
completes or fails.

## User experience

Each long operation renders one activity panel at the point where the cataloger
started it. While work is active, the panel is expanded and contains:

- a phase label such as **Preparing**, **Previewing**, **Applying**, or
  **Finalizing**;
- a plain-language description of the operation;
- a progress bar and `processed / total records` message when record progress
  is available; and
- no implication that the browser is idle while the sandbox is running.

When work finishes, the panel collapses to a one-line completed or failed
status. The final state remains visible alongside the resulting preview,
history, version, or download evidence. A failure includes the existing
bounded actionable error; it does not replace or reinterpret engine errors.

Quick paths call `st.rerun()` after storing a successful preview or export, so
their completion panel cannot remain in the original script run. The helper
therefore writes a small serializable completion summary to session state
(operation identity, phase, state, label, and bounded message) before the
rerun. The next render reads and displays that summary as a collapsed status
beside the resulting evidence, then retains it until the operation changes or
the next operation starts. Saved-task runs may display the final status in the
same run and need no summary record, but use the same helper lifecycle.

## Scope

The shared activity presentation is used by:

- Quick Find and replace preview and apply;
- focused Quick field-change preview and apply;
- specialized Quick batch preview and apply; and
- saved-task sandbox runs, which already use an expanded `st.status` panel.

The activity helper is presentation-only. It does not move work to a worker,
change the subprocess sandbox, alter cancellation or timeout behavior, or add
database or file state. Its bounded completion summary is intentionally
session state so it can survive a Streamlit rerun. Existing operation request,
preview, stale-state, audit,
snapshot, job-file-version, and export boundaries remain authoritative.

## Shared helper

Add a small renderer-facing helper, `marcedit_web/render/operation_activity.py`,
with a context-managed activity object. The helper owns the `st.status` panel,
an optional `st.progress` bar, and a status-message placeholder. On entry it
writes the supplied initial phase as `"{phase}…"`; callers then replace that
text with a bounded phase description. Its interface
supports:

- starting with an operation label and initial phase;
- updating the phase and bounded human-readable message;
- receiving `(processed, total)` progress callbacks with throttled UI writes;
- marking completion with a collapsed final label; and
- marking failure with a collapsed error label while leaving the caller's
  existing error rendering intact.

The helper must tolerate `total <= 0`, avoid division by zero, and clear its
progress/message placeholders after the final state is rendered. When the
total is zero or unknown, it must show an explicit "Progress unavailable —
processing records…" message instead of a silent zero bar. It must not write
operation values, record content, or exception tracebacks into the UI.

## Data flow by engine

Quick field changes already expose a progress callback through the sandbox
adapter runner. The Tasks renderer passes the helper callback to
`build_preview` and `build_apply_candidate`, while the helper describes the
phase transitions around input preparation, sandbox execution, and finalizing
the candidate.

Quick batch operations already expose throttled progress updates. Their local
progress/status construction moves behind the shared helper without changing
the callback cadence or operation-specific result rendering. The helper reuses
the existing `_quick_batch_progress` cadence: `min_step=250`, with updates on
the first, last, and 250-record boundaries, rather than introducing a second
throttle.

Quick Find and replace currently has no record-progress callback because its
preview first builds a bounded matching subset. It still uses the helper for
phase-only feedback: preparing the matching subset, previewing in the sandbox,
and finalizing the preview or apply result. Adding a new matcher callback is
out of scope.

Saved-task runs in `_execute_synchronous_run` retain their current messages
and sandbox calls but use the same helper lifecycle, so the visible treatment
is consistent across task and Quick workflows.

## Error and rerun behavior

The helper is synchronous and scoped to one Streamlit script run. It must not
store a live status object in session state; only the bounded serializable
completion summary may cross a rerun. On exceptions, timeout, cancellation, or
nonzero sandbox exit, the caller updates the activity to an error state and
continues using its existing bounded error path. On success, the caller writes
the completion summary before any `st.rerun()` used to refresh the resulting
evidence, and the next render displays that summary beside the evidence.

Existing engine cleanup remains responsible for preview and candidate
artifacts. The helper only closes UI placeholders; it never deletes files.

## Accessibility and wording

The status label is rendered before the operation controls' result area and is
plain language rather than implementation terminology. Progress messages use
grouped thousands separators and identify the operation phase. The final
state remains text-readable for screen readers; color and the small Streamlit
activity indicator are supplementary, not the only signal.

## Testing strategy

Add renderer-helper tests with a fake Streamlit implementation that records:

- initial expanded status and phase message;
- throttled progress updates and `processed / total` wording;
- collapsed complete and error updates; and
- cleanup of progress/message placeholders.

Add integration-facing renderer tests proving Quick Find and replace, focused
Quick field changes, Quick batch operations, and saved-task runs invoke the
same lifecycle while preserving their existing request/result calls. Existing
operation-specific tests remain unchanged except for their status assertions.
Include a rerun test proving a Quick completion summary is rendered after the
preview/export rerun and is cleared when the operation changes.

The authenticated Docker browser check must verify that a long Quick preview
shows an in-page expanded activity panel while running and a collapsed final
status after completion, with no loss of the preview evidence or download
controls.

## Non-goals

- No background worker or queue integration.
- No change to operation semantics, sandbox limits, cancellation, timeout, or
  persistence.
- No global toast system or custom JavaScript.
- No attempt to estimate progress for Find and replace beyond its existing
  phase messages.
