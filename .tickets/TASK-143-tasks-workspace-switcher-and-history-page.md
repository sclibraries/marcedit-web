Title: Tasks workspace switcher + top-level History & Export page

Scope:
- Restructure the Tasks page into a three-mode workspace switcher
  (Run / Quick operations / Build & import) so only one mode renders
  at a time, eliminating the single long vertical stack.
- Remove the session run-history and job-snapshots sections from the
  Tasks page.
- Add a new top-level "History" sidebar page showing the loaded file's
  change timeline (upload origin + every provenance snapshot: task
  runs, quick batch ops, editor edits, fixed-field edits) with
  per-entry download/diff/restore and a prominent "Export current
  file" banner.
- History page keys off the loaded file's backing job (real job or
  the invisible quick-load default job) and never uses the word "job"
  in quick-load mode.
- Jobs page and Workspace page behavior unchanged (Workspace inherits
  the Tasks restructure via the shared renderer).

Success Criteria:
- Tasks page renders exactly one mode at a time; switcher state
  survives Streamlit reruns.
- Quick find/replace and quick batch operations appear under the
  Quick operations mode instead of bottom-of-page expanders.
- History page lists snapshots metadata-only (no snapshot bytes read
  until the user requests a download/diff/restore).
- Export banner shows filename, record count, and count of changes
  since upload; export downloads current loaded-batch bytes.
- With no file loaded, History shows recent files from the user's
  jobs instead of an empty page.
- Focused tests cover the mode switcher, the timeline listing, and
  the memory-safe export/download path.

Status: In-Progress

Spec: docs/superpowers/specs/2026-07-09-tasks-workspace-and-history-design.md (local-only)
