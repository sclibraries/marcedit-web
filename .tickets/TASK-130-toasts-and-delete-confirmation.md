# TASK-130 — Action toasts and delete confirmation for job files table

**Status:** In-Progress
**Priority:** Tier 2 — Data-loss guard + feedback
**Depends on:** TASK-129
**Spec:** docs/superpowers/specs/2026-07-08-toasts-and-delete-confirmation-design.md (local)

## Title

Add action toasts (load/remove/delete) and a delete-confirmation modal to
the shared job files table.

## Problem

The table gives no feedback on load/remove/delete, and "Delete file
permanently" fires on a single click while the ⋮ popover stays open — the
user accidentally deleted several files with no warning that deletion is
unrecoverable.

## Scope

- `session.queue_toast(message, icon)` + flush in `session.init()` so
  toasts survive `st.rerun()` / `st.switch_page`.
- Shared table queues toasts: `📂 Loaded {file} — {n} record(s)`,
  `🗂️ Removed {file} from this job.`, `🗑️ Deleted {file} permanently.`
- Delete trigger now sets `{key_prefix}_pending_delete` and reruns; while
  set, a lazily-decorated `@st.dialog` confirmation renders (filename,
  record count, "cannot be undone" warning, Delete permanently / Cancel).
  Only confirm runs the delete path (remove_upload → detach → toast).
- Soft Remove stays one click (user decision); failure paths keep
  `st.error`.

## Success Criteria

1. Queued toasts flush exactly once on the next `init()`.
2. Clicking the delete trigger never calls `remove_upload`; it opens the
   confirmation dialog.
3. Cancel deletes nothing and clears the pending flag.
4. Confirmed delete calls `remove_upload(delete_file=True)`, detaches the
   loaded batch (TASK-128), queues the 🗑️ toast, clears the flag.
5. Focused suites pass locally and in Docker.
