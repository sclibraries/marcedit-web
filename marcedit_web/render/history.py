"""History & Export — the loaded file's change timeline (TASK-143).

Every mutating flow (task runs, quick batch ops, quick find/replace,
MarcEditor edits, fixed-field edits) records a before/after snapshot
via ``lib.snapshot_actions`` keyed to the backing job. This page is
the one place that shows that timeline and answers "where is my final
file?" — including for Quick Load sessions, which are backed by the
user's invisible default job. Copy on this page therefore never says
"job" unless the backing job is a real named one.

Memory rules (TASK-035 / TASK-142): the timeline lists snapshot rows
metadata-only; bytes are read from disk only when the user explicitly
prepares a download, opens a diff, or restores.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from marcedit_web.lib import (
    job_files,
    jobs,
    provenance,
    session,
    task_diff,
)
from marcedit_web.lib.audit import audit_event
from marcedit_web.lib.identity import is_anonymous
from marcedit_web.render import job_files as job_files_render

logger = logging.getLogger("marcedit_web.render.history")

K_EXPORT = "history_export"
K_OPEN_DIFF = "history_open_diff"  # one open diff at a time — caps memory

_KIND_ICONS = {
    "task-run": "▶",
    "quick-batch": "⚡",
    "quick-replace": "✨",
    "edit": "✏️",
}
_RECENT_FILES_CAP = 10


def render() -> None:
    """Render the History page content."""
    user = session.current_user_id()
    if is_anonymous(user):
        st.info("Sign in to see the change history for your files.")
        return
    if not session.has_upload():
        _render_recent_files(user)
        return

    job_id = st.session_state.get("current_job_id")
    rows = provenance.list_snapshots(int(job_id)) if job_id else []

    if job_id is None:
        _render_export_banner(rows)
        st.info(
            "History is recorded once the file is stored in your "
            "workspace. Re-load the file from **Home** to enable it."
        )
        return

    file_id = st.session_state.get("job_file_id")
    if file_id is not None and not st.session_state.get(
        "quick_load_mode", False
    ):
        versions = job_files.list_versions(int(file_id), user)
        _render_export_banner(rows, change_count=max(len(versions) - 1, 0))
        _render_job_file_history(
            int(job_id), int(file_id), user, rows, versions
        )
        return

    _render_export_banner(rows)
    _render_workspace_header(int(job_id))
    if not rows:
        st.info(
            "No recorded changes yet. Task runs, quick operations, and "
            "editor changes will appear here."
        )
    for row in rows:
        _render_snapshot_entry(row)
    _render_origin_entry(int(job_id))


def _render_job_file_history(
    job_id: int,
    file_id: int,
    user: str,
    legacy_rows: list[dict],
    versions: list[dict],
) -> None:
    """Render immutable history and review controls for one exact job file."""
    file_row = job_files.get_file(file_id, user)
    notes = jobs.list_review_notes(
        job_id,
        user_email=user,
        job_file_id=file_id,
    )
    st.subheader(f"History & review — {file_row['display_name']}")
    current_number = next(
        (
            row["version_number"]
            for row in versions
            if row["id"] == file_row["current_version_id"]
        ),
        None,
    )
    current_label = (
        f"v{current_number}" if current_number is not None else "unknown"
    )
    st.caption(
        f"{file_row['status'].replace('_', ' ').capitalize()} · "
        f"current version {current_label}"
    )
    _render_file_transition_controls(file_row, user)
    job_files_render.render_file_exports(
        file_row,
        user=user,
        opened_version_id=st.session_state.get("job_file_version_id"),
    )
    can_restore = _can_restore_file(file_row, user)

    st.markdown("**Immutable version history**")
    versions_by_id = {int(row["id"]): row for row in versions}
    notes_by_version: dict[int | None, list[dict]] = {}
    for note in notes:
        version_id = note.get("job_file_version_id")
        notes_by_version.setdefault(
            int(version_id) if version_id is not None else None,
            [],
        ).append(note)
    for version in reversed(versions):
        _render_file_version_entry(
            version,
            versions_by_id,
            notes_by_version.get(int(version["id"]), []),
            is_current=int(version["id"]) == int(file_row["current_version_id"]),
            can_restore=can_restore,
        )
    for note in notes_by_version.get(None, []):
        _render_review_note(note)

    if legacy_rows:
        st.subheader("Legacy job history")
        st.caption(
            "These retained job snapshots could not be deterministically linked "
            "to one file version."
        )
        for row in legacy_rows:
            _render_snapshot_entry(row)


def _render_file_transition_controls(file_row: dict, user: str) -> None:
    if file_row.get("access_role") not in {"owner", "editor"}:
        return
    file_id = int(file_row["id"])
    opened_version_id = st.session_state.get("job_file_version_id")
    if opened_version_id is None:
        st.warning("Reopen this file before changing its review state.")
        return
    status = str(file_row["status"])
    cols = st.columns(3)
    if status in {"new", "in_progress", "changes_requested"} and cols[0].button(
        "Return for review",
        key=f"file_review_return_{file_id}",
    ):
        _run_file_transition(
            job_files.return_for_review,
            file_id,
            user,
            int(opened_version_id),
        )
    if status in {"in_progress", "needs_review"} and cols[1].button(
        "Approve current",
        key=f"file_review_approve_{file_id}",
    ):
        _run_file_transition(
            job_files.approve_current,
            file_id,
            user,
            int(opened_version_id),
        )
    if status in {"approved", "exported"} and cols[2].button(
        "Mark complete",
        key=f"file_review_complete_{file_id}",
    ):
        _run_file_transition(
            job_files.set_complete,
            file_id,
            user,
            int(opened_version_id),
        )
    if status == "needs_review":
        note = st.text_area(
            "Change request note",
            key=f"file_review_change_note_{file_id}",
        )
        if st.button(
            "Request changes",
            key=f"file_review_changes_{file_id}",
        ):
            try:
                job_files.request_changes(
                    file_id,
                    by=user,
                    opened_version_id=int(opened_version_id),
                    note=note,
                )
            except job_files.JobFileError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    review_note = st.text_area(
        "Review note",
        key=f"file_review_note_{file_id}",
    )
    if st.button(
        "Add review note",
        key=f"file_review_add_note_{file_id}",
    ):
        try:
            jobs.add_review_note(
                int(file_row["job_id"]),
                anchor_kind="job_file",
                note=review_note,
                author=user,
                job_file_id=file_id,
                job_file_version_id=int(opened_version_id),
            )
        except jobs.JobError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def _run_file_transition(function, file_id: int, user: str, version_id: int) -> None:
    try:
        function(file_id, by=user, opened_version_id=version_id)
    except job_files.JobFileError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _render_file_version_entry(
    version: dict,
    versions_by_id: dict[int, dict],
    notes: list[dict],
    *,
    is_current: bool,
    can_restore: bool,
) -> None:
    current_label = " · current" if is_current else ""
    st.markdown(
        f"**v{version['version_number']}{current_label}** — "
        f"{version['source_kind']} · {version['label'] or '(no label)'}"
    )
    st.caption(f"By {version['created_by']} · {version['created_at']}")
    if version.get("approval_kind"):
        st.caption(
            f"{version['approval_kind']} by {version['approved_by']} · "
            f"{version['approved_at']}"
        )
    summary = version.get("summary_json") or "{}"
    validation = version.get("validation_json") or "{}"
    if summary != "{}":
        st.write(f"Summary: {summary}")
    if validation != "{}":
        st.write(f"Validation: {validation}")
    parent_id = version.get("parent_version_id")
    if parent_id is not None and int(parent_id) in versions_by_id:
        parent = versions_by_id[int(parent_id)]
        before = Path(parent["file_path"])
        after = Path(version["file_path"])
        if before.exists() and after.exists():
            column = st.columns(1)[0]
            _offer_diff(
                column,
                {
                    "id": f"file-version-{version['id']}",
                    "before_path": str(before),
                    "after_path": str(after),
                },
                before,
                after,
            )
    if can_restore and not is_current and st.button(
        "Restore as new version",
        key=f"file_version_restore_{version['id']}",
    ):
        try:
            _restore_version(int(version["id"]))
        except job_files.JobFileError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    for note in notes:
        _render_review_note(note)
    st.divider()


def _can_restore_file(file_row: dict, user: str) -> bool:
    """Return whether the exact open version may be restored by this viewer."""
    from marcedit_web.render import job_files as job_files_render

    if file_row.get("access_role") not in {"owner", "editor"}:
        return False
    opened_version_id = st.session_state.get("job_file_version_id")
    if opened_version_id is None or int(opened_version_id) != int(
        file_row["current_version_id"]
    ):
        return False
    checkout = job_files_render._active_checkout(int(file_row["id"]))
    return checkout is not None and checkout["holder_email"] == user


def _render_review_note(note: dict) -> None:
    state = "Resolved" if note["resolved"] else "Open"
    st.write(f"{state} note: {note['note']}")
    st.caption(f"{note['author_email']} · {note['created_at']}")


# ---------------------------------------------------------------------------
# Export banner
# ---------------------------------------------------------------------------


def _render_export_banner(
    rows: list[dict],
    *,
    change_count: int | None = None,
) -> None:
    store = session.current_store()
    if store is None:
        return
    filename = session.current_filename() or "(unnamed)"
    changes = len(rows) if change_count is None else change_count
    st.markdown(
        f"**Current file:** `{filename}` · {store.count():,} records · "
        f"{changes} recorded change{'s' if changes != 1 else ''}"
    )

    export = st.session_state.get(K_EXPORT)
    if export and (
        export.get("snapshot_count") != changes
        or export.get("source_filename") != filename
        or export.get("job_id") != st.session_state.get("current_job_id")
    ):
        # The batch changed, or a different file/job is now loaded, since
        # the export was prepared — a stale download would silently miss
        # the newest changes or serve the wrong file's bytes.
        _cleanup_export(export)
        st.session_state.pop(K_EXPORT, None)
        export = None

    if export is None:
        if st.button(
            "Prepare export of current file",
            type="primary",
            key="history_export_prepare",
            help=(
                "Writes the current batch to a temporary file and "
                "offers a download button. Two-step gate avoids "
                "re-serializing large batches on every page refresh."
            ),
        ):
            try:
                _prepare_export(store, filename, changes)
            except Exception:  # noqa: BLE001 — surface, don't cache
                logger.exception("history export preparation failed")
                st.error(
                    "Could not prepare the export — see the server log."
                )
            else:
                st.rerun()
        return

    path = Path(export["path"])
    if not path.exists():
        _cleanup_export(export)
        st.session_state.pop(K_EXPORT, None)
        st.caption("The prepared export is gone — prepare it again.")
        return
    st.download_button(
        "⬇ Export current file",
        data=path.read_bytes(),
        file_name=export["filename"],
        mime="application/marc",
        key="history_export_download",
    )
    st.divider()


def _prepare_export(store, filename: str, snapshot_count: int) -> None:
    _cleanup_export(st.session_state.get(K_EXPORT))
    stem = Path(filename).stem or "export"
    out_name = session.stamped_filename(f"{stem}_export", ".mrc")
    export_dir = Path(tempfile.mkdtemp(prefix="marcedit-web-history-"))
    path = export_dir / out_name
    store.write_mrc_to(path)
    st.session_state[K_EXPORT] = {
        "path": str(path),
        "filename": out_name,
        "snapshot_count": snapshot_count,
        "source_filename": filename,
        "job_id": st.session_state.get("current_job_id"),
    }


def _cleanup_export(export: dict | None) -> None:
    if not export:
        return
    path_str = export.get("path")
    if not path_str:
        return
    path = Path(path_str)
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        logger.warning("could not remove export temp file %s", path_str)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def _render_workspace_header(job_id: int) -> None:
    job = jobs.get_job(job_id)
    if job and job.get("name") != jobs.DEFAULT_JOB_NAME:
        st.subheader(f"Change history — {job['name']}")
    else:
        st.subheader("Change history")


def _render_snapshot_entry(row: dict) -> None:
    icon = _KIND_ICONS.get(row["kind"], "•")
    summary = _snapshot_summary(row)
    st.markdown(
        f"**{row['created_at']}** — {icon} {row['label'] or '(no label)'}"
    )
    st.caption(
        f"By {row['user_email']}" + (f" · {summary}" if summary else "")
    )

    before = Path(row["before_path"]) if row.get("before_path") else None
    after = Path(row["after_path"]) if row.get("after_path") else None
    if not (before and before.exists() and after and after.exists()):
        st.caption(
            "The stored bytes for this change are no longer available "
            "(pruned or cleaned up); only this summary remains."
        )
        st.divider()
        return

    is_job_file = (
        st.session_state.get("job_file_id") is not None
        and not st.session_state.get("quick_load_mode", False)
    )
    cols = st.columns(3 if is_job_file else 4)
    download_offset = 0
    if not is_job_file and cols[0].button(
        "Restore pre-change version",
        key=f"snapshot_restore_{row['id']}",
        help="Replace the current loaded batch with this snapshot's before state.",
    ):
        source_path = provenance.restore_path(int(row["id"]))
        filename = session.current_filename() or f"snapshot-{row['id']}.mrc"
        session.replace_current_store_from_path(
            source_path,
            filename=filename,
            job_id=int(row["job_id"]),
        )
        # The restore didn't add a snapshot, so the staleness guard above
        # (which only compares snapshot counts) wouldn't catch a
        # previously-prepared export — it would keep serving pre-restore
        # bytes. Drop it explicitly (TASK-143).
        _cleanup_export(st.session_state.get(K_EXPORT))
        st.session_state.pop(K_EXPORT, None)
        audit_event(
            "job-snapshot-restored",
            user=session.current_user_id(),
            snapshot_id=row["id"],
            job_id=row["job_id"],
            snapshot_kind=row["kind"],
        )
        st.success(
            "Restored the pre-change version into the current session."
        )
        st.rerun()
    if not is_job_file:
        download_offset = 1

    _offer_history_download(
        cols[download_offset],
        row.get("before_path"),
        "Download before",
        f"snapshot_{row['id']}_before.mrc",
        key=f"snapshot_before_{row['id']}",
    )
    _offer_history_download(
        cols[download_offset + 1],
        row.get("after_path"),
        "Download after",
        f"snapshot_{row['id']}_after.mrc",
        key=f"snapshot_after_{row['id']}",
    )
    _offer_diff(cols[download_offset + 2], row, before, after)
    st.divider()


def _restore_version(version_id: int) -> dict:
    user = session.current_user_id()
    selected = job_files.get_version(version_id, user)
    current_file_id = st.session_state.get("job_file_id")
    if current_file_id is None or int(selected["job_file_id"]) != int(
        current_file_id
    ):
        raise job_files.JobFileError(
            "The selected version does not belong to the open job file."
        )
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-restore-"))
    candidate = workdir / "candidate.mrc"
    try:
        shutil.copyfile(Path(selected["file_path"]), candidate)
        return session.adopt_current_candidate(
            candidate_path=candidate,
            source_kind="restore",
            label=f"Restore version {selected['version_number']}",
            summary={"restored_version_id": selected["id"]},
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _offer_diff(column, row: dict, before: Path, after: Path) -> None:
    open_diff = st.session_state.get(K_OPEN_DIFF)
    is_open = bool(open_diff) and open_diff["snapshot_id"] == row["id"]
    if not is_open:
        if column.button("Show diff", key=f"snapshot_diff_{row['id']}"):
            # One diff at a time: replacing K_OPEN_DIFF frees the prior
            # summary, so long review sessions can't pile up diffs.
            st.session_state[K_OPEN_DIFF] = {
                "snapshot_id": row["id"],
                "summary": task_diff.compute_task_diff(
                    before, after
                ),
            }
            st.rerun()
        return
    if column.button("Hide diff", key=f"snapshot_diff_hide_{row['id']}"):
        st.session_state.pop(K_OPEN_DIFF, None)
        st.rerun()
    _render_diff_summary(open_diff["summary"])


def _render_diff_summary(summary) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Changed records", summary.changed_count)
    c2.metric("Unchanged records", summary.unchanged_count)
    c3.metric(
        "Tags touched",
        len(
            set(summary.per_tag_added)
            | set(summary.per_tag_deleted)
            | set(summary.per_tag_modified)
        ),
    )
    tags = sorted(
        set(summary.per_tag_added)
        | set(summary.per_tag_deleted)
        | set(summary.per_tag_modified)
    )
    if tags:
        st.table(
            [
                {
                    "Tag": tag,
                    "Added": summary.per_tag_added.get(tag, 0),
                    "Deleted": summary.per_tag_deleted.get(tag, 0),
                    "Modified": summary.per_tag_modified.get(tag, 0),
                }
                for tag in tags
            ]
        )
    if summary.changed_count == 0:
        st.info("This change modified no records.")


def _snapshot_summary(row: dict) -> str:
    try:
        summary = json.loads(row.get("summary_json") or "{}")
    except json.JSONDecodeError:
        return ""
    parts = []
    if "changed_count" in summary:
        parts.append(f"{summary['changed_count']} changed")
    if "error_count" in summary:
        parts.append(f"{summary['error_count']} errors")
    return ", ".join(parts)


def _render_origin_entry(job_id: int) -> None:
    filename = session.current_filename()
    uploads = [
        u
        for u in jobs.list_job_uploads(job_id)
        if u["filename"] == filename
    ]
    if not uploads:
        return
    origin = uploads[-1]  # newest matching upload
    st.markdown(
        f"**{origin['uploaded_at']}** — 📤 Uploaded "
        f"`{origin['filename']}` ({origin['record_count']:,} records)"
    )
    cols = st.columns(4)
    _offer_history_download(
        cols[0],
        origin.get("file_path"),
        "Download original",
        origin["filename"],
        key=f"history_origin_{origin['id']}",
    )


def _offer_history_download(
    column,
    path_str: str | None,
    label: str,
    file_name: str,
    *,
    key: str,
) -> None:
    """Two-step prepare → download for a historical file (TASK-035).

    ``download_button`` materializes its ``data`` eagerly, so
    rendering one per row would pin every row's bytes on every
    refresh. First render shows "Prepare"; clicking sets a per-row
    ready flag; the next render reads the bytes once.
    """
    if not path_str:
        column.caption("(no file recorded)")
        return
    path = Path(path_str)
    if not path.exists():
        column.button(
            label,
            disabled=True,
            help="The stored file is no longer available.",
            key=f"{key}_missing",
        )
        return

    ready_key = f"{key}_ready"
    if not st.session_state.get(ready_key):
        if column.button(
            f"Prepare {label}",
            key=f"{key}_prepare",
            help=(
                "Loads the file from disk and offers a download "
                "button. Two-step gate avoids re-reading large "
                "historical files on every page refresh."
            ),
        ):
            st.session_state[ready_key] = True
            st.rerun()
        return

    column.download_button(
        label,
        data=path.read_bytes(),
        file_name=file_name,
        mime="application/marc",
        key=key,
    )


# ---------------------------------------------------------------------------
# No-batch fallback
# ---------------------------------------------------------------------------


def _render_recent_files(user: str) -> None:
    st.info(
        "No MARC batch is loaded. Load a recent file below, or upload "
        "one on the **Home** page."
    )
    rows: list[dict] = []
    for job in jobs.list_job_summaries(user):
        rows.extend(jobs.list_job_uploads(int(job["id"])))
    if not rows:
        st.caption("No stored files yet.")
        return
    rows.sort(key=lambda r: str(r["uploaded_at"]), reverse=True)
    for row in rows[:_RECENT_FILES_CAP]:
        cols = st.columns([4, 1, 2, 1])
        cols[0].write(row["filename"])
        cols[1].write(f"{row['record_count']:,}")
        cols[2].write(str(row["uploaded_at"]))
        if cols[3].button("Load", key=f"history_load_{row['id']}"):
            summary = session.load_persisted_upload(int(row["id"]))
            if summary.get("error"):
                st.error(summary["error"])
            else:
                st.rerun()
