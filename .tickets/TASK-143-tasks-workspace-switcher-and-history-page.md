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

Discovered during verification (fixed on this branch):
- Quick find/replace applied without recording a provenance snapshot
  (kind "quick-replace" added; the History timeline was the feature
  that made the gap user-visible).
- `restore_active_upload` did not restore `current_job_id`, so a
  browser refresh silently disabled snapshot recording for every
  mutating flow and degraded the History page.
- A prepared History export survived both "Restore pre-change
  version" and switching to a different loaded file, serving stale
  bytes; the export is now invalidated on restore and keyed to
  snapshot count + source filename + job id.

Verification:
- `docker run --rm -v $WT/marcedit_web:/app/marcedit_web:ro -v $WT/tests:/app/tests:ro -v $WT/data:/app/data:ro -v $WT/docker-compose.yml:/app/docker-compose.yml:ro marcedit-web:dev pytest -ra tests/`
  - 1014 passed, 7 skipped (deploy-file tests, env-conditional).
- `python3 -m pytest -ra tests/test_deploy_units.py tests/test_docker_compose_config.py` (host)
  - 8 passed.
- Browser-driven smoke (Playwright, signed-in via header-injecting
  proxy): mode switching + rerun persistence, editor forces Build &
  import, quick find/replace apply -> quick-replace snapshot row,
  History timeline + per-entry diff + restore, export prepare/download
  round-trip (downloaded bytes verified to contain the applied
  change), no-batch recent-files fallback with Load, refresh path
  after the current_job_id fix.
- Final whole-branch code review: approved with fixes; all fixes
  applied and re-reviewed clean.

Follow-ups (see TASK-144, TASK-145):
- History interactive test-coverage gaps (diff open/replace/close,
  job-id-less render branch, anonymous quick-replace path).
- Restore creates a new upload row per restore (pre-existing), which
  grows the recent-files list and skews the timeline origin entry.

Status: Completed

Spec: docs/superpowers/specs/2026-07-09-tasks-workspace-and-history-design.md (local-only)
