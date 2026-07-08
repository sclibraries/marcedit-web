"""Shared job-files table (TASK-129).

One renderer for Home's Job Workspace and the Jobs detail page so the two
lists cannot drift apart (they did between TASK-125 and TASK-128: layout
and the delete label diverged). The layout is the TASK-126 design: a
bordered container, one vertically-centered grid row per file, a Load
button, and a ⋮ popover holding the permission-gated destructive actions
(TASK-127 load semantics, TASK-128 detach-on-delete).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from marcedit_web.lib import jobs, session

# One line per file: Filename | Records | Size | Uploaded | Status | Load | ⋮.
# Weights tuned so "Load" and the ⋮ trigger never wrap at layout="wide".
UPLOADS_GRID = [4, 1, 1, 2, 1.4, 1, 0.6]
UPLOADS_HEADERS = ("Filename", "Records", "Size", "Uploaded", "Status", "", "")

_EDIT_ROLES = {"owner", "editor"}


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def format_uploaded_at(value) -> str:
    # uploads.uploaded_at is ISO-8601 UTC ("2026-07-01T09:14:32Z");
    # catalogers scan dates, so render "Jul 1, 2026 09:14" instead.
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.strftime('%Y %H:%M')}"


def render_job_files_table(
    uploads: list[dict],
    *,
    user: str,
    role: str | None,
    key_prefix: str,
) -> None:
    """Render the actionable files table for ``uploads``.

    Callers own the section heading and the empty state; pass a non-empty
    list. ``key_prefix`` keeps each page's historical widget keys
    (``home_job_upload`` on Home, ``job_upload`` on Jobs) so click-through
    behavior and its tests survive the extraction.
    """
    # Late import: page tests swap sys.modules["streamlit"] for a fake.
    import streamlit as st

    with st.container(border=True):
        headers = st.columns(
            UPLOADS_GRID, vertical_alignment="center", gap="small"
        )
        for col, title in zip(headers, UPLOADS_HEADERS):
            if title:
                col.markdown(f"**{title}**")
        st.divider()
        for row in uploads:
            cols = st.columns(
                UPLOADS_GRID, vertical_alignment="center", gap="small"
            )
            cols[0].write(row["filename"])
            cols[1].write(f"{row['record_count']:,}")
            cols[2].write(format_size(row["file_bytes"]))
            cols[3].write(format_uploaded_at(row["uploaded_at"]))
            cols[4].markdown(
                ":green[● Current]" if row["active"] else ":gray[Available]"
            )
            if cols[5].button(
                "Load",
                key=f"{key_prefix}_load_{row['id']}",
                use_container_width=True,
            ):
                try:
                    summary = session.load_persisted_upload(int(row["id"]))
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    if summary.get("error"):
                        st.error(summary["error"])
                    else:
                        st.switch_page("views/1_View.py")
            can_remove = role in _EDIT_ROLES
            can_delete = row["user_email"] == user
            if not (can_remove or can_delete):
                continue
            with cols[6].popover("⋮"):
                if can_remove:
                    if st.button(
                        "Remove from job",
                        key=f"{key_prefix}_remove_{row['id']}",
                        use_container_width=True,
                    ):
                        try:
                            jobs.remove_upload(int(row["id"]), by=user)
                        except jobs.JobError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
                    st.caption("Keeps the stored file; hides it from this job.")
                if can_delete:
                    if st.button(
                        "Delete file permanently",
                        key=f"{key_prefix}_delete_{row['id']}",
                        use_container_width=True,
                    ):
                        try:
                            jobs.remove_upload(
                                int(row["id"]),
                                by=user,
                                delete_file=True,
                            )
                        except jobs.JobError as exc:
                            st.error(str(exc))
                        else:
                            # The deleted file may back the loaded batch;
                            # a dangling store crashes the rerun (TASK-128).
                            session.detach_loaded_batch(row["file_path"])
                            st.rerun()
                    st.caption("Deletes the stored file for everyone in the job.")
