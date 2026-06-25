# TASK-036 — Batch Find/Replace Preview

**Status:** Completed
**Stage:** First stage of v3.2 (Guided Batch Editing And Validation).

## Title

A cataloger today who wants to "fix this one typo across 100 records"
has to know what tasks are, build one, save it, run it, review the
diff, then download. That's a lot of cognitive overhead for a
one-shot edit. Add a Quick find/replace wizard that hides the task
machinery: type tag + find + replace, click Preview, look at the
diff, click Apply. The implementation is a transient task body shipped
through the existing sandbox — no saved file, no task list entry.

## Scope

- **New module** `marcedit_web/lib/batch_replace.py`:
  * ``BatchReplaceRequest`` dataclass — tag, subfield, find, replace,
    regex, ignore_case.
  * ``validate_request(request)`` — returns error string or ``None``.
    Catches empty tag/find, bad regex syntax before sandbox.
  * ``matched_indices_for(store, request)`` — walks the live store
    and returns 0-based indices whose target tag/subfield contains a
    match for the find text (literal or regex).
  * ``fingerprint_record(record)`` — sha256 over ``record.as_marc()``
    bytes; used for stale-preview detection.
  * ``build_preview(store, request)`` — writes matched records to a
    temp subset MARC, builds a transient ``# OP`` body via the
    existing ``task_builder.render_ops_to_python`` pipeline, runs it
    through ``sandbox.run_tasks_subprocess``, parses the output, and
    returns a ``BatchReplacePreview`` containing matched indices,
    fingerprints, ``TaskDiffSummary``, and the post-transform
    ``pymarc.Record`` objects (parallel to matched_indices).
  * ``apply_preview(store, preview)`` — re-fingerprints each matched
    index against the live store; if any drifted since preview,
    refuses with the stale list; otherwise calls
    ``store.replace(idx, record)`` per pair and returns the applied
    count.
- **UI** in `render/tasks.py`:
  * New collapsed expander above the run panel: "Quick find/replace
    (no saved task)".
  * Inputs: tag, subfield (optional), find, replace, regex toggle,
    case-insensitive toggle.
  * **Preview** button — non-mutating: stores the preview in
    session_state, renders matched-count + per-tag diff summary +
    "Show per-record diffs" expander (reusing TASK-023 layout).
  * **Apply** button — only enabled after a preview; refuses on
    stale fingerprints with a clear error pointing at the changed
    indices.
  * **Reset** button — drops the preview state without applying.
- **Audit**: emit ``batch-replace-applied`` on Apply success (user,
  filename, matched_count, changed_count, tag, subfield, regex,
  applied_indices_count). Preview is silent — building a preview
  isn't a security event.
- **Tests** `tests/test_batch_replace.py`:
  * ``validate_request`` empty-tag / empty-find / bad regex.
  * ``matched_indices_for`` literal + regex + subfield-filter +
    ignore_case + no-match.
  * ``build_preview`` end-to-end on the sample fixture: returns
    expected match count and applied diff (sandbox-driven).
  * ``apply_preview`` happy path mutates the store.
  * ``apply_preview`` stale-detection: mutate a record between
    preview and apply, confirm refusal.

## Out of scope

- **Sandbox driver changes.** Per the plan: write matched records
  to a temp subset, run on the subset, map output back. No changes
  to ``sandbox.run_tasks_subprocess`` or the driver script.
- **Find by byte position (008/28 etc.).** Variable-field replace
  only for v1. Fixed-field byte edits go through the 008 helper.
- **Plain-text "find anywhere" search across all fields.** The
  wizard requires a target tag; cross-field find would change the
  scope of what gets rewritten. Defer.
- **Saving the wizard input as a reusable task.** It's deliberately
  one-shot. A future stage could add a "Save as task…" button if
  catalogers ask.

## Success Criteria

1. With sample.mrc loaded, opening the wizard and previewing
   ``245$a / "title" → "Title"`` shows the expected match count
   and a non-empty changed-count.
2. Clicking Apply commits the change; View / Report reflect the
   new bytes; Run history isn't polluted (one-shot only).
3. Stale-preview refusal: edit a matched record via the inline
   editor between Preview and Apply, hit Apply — error fires,
   batch unchanged.
4. ``batch-replace-applied`` audit row lands on Apply; nothing on
   Preview.
5. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_batch_replace.py
docker compose run --rm marcedit-web pytest -q
```
