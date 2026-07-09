# TASK-136 — Action toasts and delete confirmation for job files table

**Status:** Completed
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

## Outcome

- `session.queue_toast` + flush at the end of `session.init()`; the shared
  table queues 📂/🗂️/🗑️ toasts on load/remove/delete success.
- Delete trigger sets `{key_prefix}_pending_delete` and reruns; the
  lazily-decorated `@st.dialog` confirmation (filename, record count,
  cannot-be-undone warning, primary Delete permanently / Cancel) is the
  only path to `remove_upload(delete_file=True)`, which still runs the
  TASK-128 detach. Stale pending ids are dropped silently; JobError keeps
  the dialog open with the error shown.
- Verification:
  - RED: 9 targeted failures for the intended reasons before
    implementation; toast-plumbing test failed on missing `queue_toast`.
  - GREEN local + Docker (Python 3.9 / Streamlit 1.50): 79 passed each
    (includes 2 review-requested regression tests: delete-error keeps the
    dialog, stale flag dropped).
  - Live browser check: modal renders with warning copy, confirmed delete
    removes the file, non-uploader rows show no delete action, remove
    toast appeared 200 ms after the click.
- Code review: Ready to merge (after adding the two regression tests).
- Accepted behavior (review Minor): navigating away mid-confirmation and
  returning to the same job/file reopens the dialog — the pending flag is
  keyed per page prefix, not per visit; it cannot cause an unconfirmed
  delete.

> Note: originally opened as TASK-130 in this session; renumbered to
> TASK-136 because a parallel session claimed TASK-130 (align max upload
> size) on main first.
