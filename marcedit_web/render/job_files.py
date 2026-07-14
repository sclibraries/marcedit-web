"""Shared job-file attachment and table UI (TASK-151).

One renderer keeps Home's Job Workspace and the Jobs detail page on the
same attachment, open, and archive paths.
"""

from __future__ import annotations

import datetime as dt
from marcedit_web.lib import job_files, session

# One line per file; weights keep Open and the ⋮ trigger from wrapping.
UPLOADS_GRID = [3, 1.5, 1, 1, 2, 2, 1, 0.6]
UPLOADS_HEADERS = (
    "Name", "Status", "Version", "Records", "Last editor", "Updated", "", ""
)

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
    files: list[dict],
    *,
    user: str,
    role: str | None,
    key_prefix: str,
) -> None:
    """Render the actionable files table for accessible work files.

    Callers own the section heading and the empty state; pass a non-empty
    list. ``key_prefix`` keeps each page's widget state independent.
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
        for row in files:
            cols = st.columns(
                UPLOADS_GRID, vertical_alignment="center", gap="small"
            )
            cols[0].write(row["display_name"])
            cols[1].write(row["status"].replace("_", " ").capitalize())
            cols[2].write(f"v{row['current_version_number']}")
            cols[3].write(f"{row['current_record_count']:,}")
            cols[4].write(row["updated_by"])
            cols[5].write(format_uploaded_at(row["updated_at"]))
            if cols[6].button(
                "Open",
                key=f"{key_prefix}_load_{row['id']}",
                use_container_width=True,
            ):
                try:
                    summary = session.open_job_file(int(row["id"]))
                except job_files.JobFileError as exc:
                    st.error(str(exc))
                else:
                    total = int(summary.get("total", 0))
                    session.queue_toast(
                        f"Opened {row['display_name']} — {total:,} "
                        f"record{'s' if total != 1 else ''}",
                        icon="📂",
                    )
                    st.switch_page("views/1_View.py")
            can_remove = role in _EDIT_ROLES
            if not can_remove:
                continue
            with cols[7].popover("⋮"):
                if st.button(
                    "Remove from job",
                    key=f"{key_prefix}_remove_{row['id']}",
                    use_container_width=True,
                ):
                    try:
                        job_files.archive_file(int(row["id"]), by=user)
                    except job_files.JobFileError as exc:
                        st.error(str(exc))
                    else:
                        session.queue_toast(
                            f"Archived {row['display_name']}.",
                            icon="🗂️",
                        )
                        st.rerun()
                st.caption("Keeps every version and export; hides this file.")


def render_upload_feedback(upload_summary: dict) -> None:
    """Render the shared Home/Jobs upload result."""
    import streamlit as st

    if upload_summary.get("error"):
        st.error(
            f"Upload rejected: {upload_summary['error']}. Contact ops if "
            "you need a higher limit for this batch."
        )
    elif upload_summary["total"] == 0 and upload_summary["malformed"] == 0:
        st.error("No records found in the uploaded file.")
    else:
        st.success(
            f"Loaded **{upload_summary['total']}** record"
            f"{'s' if upload_summary['total'] != 1 else ''} from "
            f"`{upload_summary['filename']}`."
        )
        if upload_summary["malformed"]:
            st.warning(
                f"{upload_summary['malformed']} record"
                f"{'s' if upload_summary['malformed'] != 1 else ''} could not be "
                "parsed and will be skipped."
            )


def render_attach_file(
    job_id: int,
    user: str,
    role: str | None,
    key_prefix: str,
) -> None:
    """Render the one shared, permission-gated job attachment path."""
    if role not in _EDIT_ROLES:
        return
    import streamlit as st

    description = st.text_input(
        "File description (optional)", key=f"{key_prefix}_description"
    )
    nonce_key = f"{key_prefix}_nonce"
    summary_key = f"{key_prefix}_summary"
    uploaded = st.file_uploader(
        "Attach MARC file",
        type=["mrc", "marc"],
        accept_multiple_files=False,
        key=f"{key_prefix}_upload_{st.session_state.get(nonce_key, 0)}",
    )
    if uploaded is None:
        summary = st.session_state.get(summary_key)
        if summary and summary.get("job_id") == job_id:
            render_upload_feedback(summary)
        return
    with st.spinner(f"Parsing {uploaded.name}…"):
        summary = session.handle_upload(
            uploaded,
            job_id=job_id,
            description=description,
        )
    summary = {**summary, "job_id": job_id}
    if summary.get("error") or not summary.get("total"):
        render_upload_feedback(summary)
        return
    st.session_state[summary_key] = summary
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1
    st.rerun()
