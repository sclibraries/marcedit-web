"""Jobs workspace page (TASK-118)."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import jobs, session
from marcedit_web.lib.identity import is_anonymous

_DETAIL_UNAVAILABLE = "Job not found or unavailable."


def _status_label(status: str) -> str:
    return status.replace("_", " ").capitalize()


def _can_edit(role: str | None) -> bool:
    return role in {"owner", "editor"}


def _can_manage(role: str | None) -> bool:
    return role == "owner"


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _render_list(user: str) -> None:
    st.title("Jobs")
    st.caption("Shared cataloging workspaces for vendor loads, review, and handoff.")

    include_archived = st.toggle("Show archived", value=False, key="jobs_show_archived")
    rows = jobs.list_job_summaries(user, include_archived=include_archived)
    if not rows:
        st.info("No jobs found.")
        return

    for row in rows:
        with st.container(border=True):
            cols = st.columns([4, 2, 2, 1, 1, 2])
            cols[0].subheader(row["name"])
            cols[1].write(_status_label(row["status"]))
            cols[2].write(row["owner_email"])
            cols[3].write(f"{row['file_count']} file(s)")
            cols[4].write(f"{row['open_note_count']} open")
            if cols[5].button("Open", key=f"open_job_{row['id']}"):
                st.session_state["selected_job_detail_id"] = row["id"]
                st.rerun()


def _render_detail(user: str, job_id: int) -> None:
    role = jobs.get_access_role(job_id, user)
    if role is None:
        st.error(_DETAIL_UNAVAILABLE)
        return
    job = jobs.get_job(job_id)
    if job is None:
        st.error(_DETAIL_UNAVAILABLE)
        return

    if st.button("Back to jobs", key="jobs_back"):
        st.session_state.pop("selected_job_detail_id", None)
        st.rerun()
    st.title(job["name"])
    st.caption(f"{_status_label(job['status'])} · {role} · owned by {job['owner_email']}")

    st.subheader("Status")
    if _can_edit(role):
        current_index = jobs.JOB_STATUSES.index(job["status"])
        selected_status = st.selectbox(
            "Workflow status",
            jobs.JOB_STATUSES,
            index=current_index,
            format_func=_status_label,
            key=f"job_status_{job_id}",
        )
        status_note = st.text_input(
            "Status note",
            key=f"job_status_note_{job_id}",
            placeholder="Optional handoff note",
        )
        if st.button("Update status", key=f"job_status_update_{job_id}"):
            try:
                jobs.set_status(
                    job_id,
                    selected_status,
                    by=user,
                    note=status_note,
                )
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    else:
        st.write(_status_label(job["status"]))

    uploads = jobs.list_job_uploads(job_id)
    st.subheader("Files")
    if uploads:
        st.dataframe(
            [
                {
                    "Filename": row["filename"],
                    "Records": row["record_count"],
                    "Size": _format_size(row["file_bytes"]),
                    "Uploaded": row["uploaded_at"],
                    "Active": bool(row["active"]),
                }
                for row in uploads
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No files uploaded to this job yet.")

    st.subheader("Sharing")
    access_rows = jobs.list_access(job_id)
    st.dataframe(access_rows, hide_index=True, use_container_width=True)
    if _can_manage(role):
        share_email = st.text_input(
            "Cataloger email",
            placeholder="name@example.edu",
            key=f"job_share_email_{job_id}",
        )
        share_role = st.selectbox(
            "Role",
            ["editor", "viewer"],
            key=f"job_share_role_{job_id}",
        )
        if st.button("Grant access", key=f"job_share_grant_{job_id}"):
            try:
                jobs.grant_access(job_id, share_email, share_role, by=user)
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.rerun()

        revoke_options = [
            row["user_email"] for row in access_rows if row["role"] != "owner"
        ]
        if revoke_options:
            revoke_email = st.selectbox(
                "Remove access",
                revoke_options,
                key=f"job_share_revoke_email_{job_id}",
            )
            if st.button("Revoke access", key=f"job_share_revoke_{job_id}"):
                try:
                    jobs.revoke_access(job_id, revoke_email, by=user)
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()

    st.subheader("Review notes")
    notes = jobs.list_review_notes(job_id, user_email=user)
    if notes:
        for note in notes:
            with st.container(border=True):
                state = "Resolved" if note["resolved"] else "Open"
                st.write(
                    f"**{state}** · {note['anchor_kind']} {note['anchor_value']}"
                )
                st.write(note["note"])
                st.caption(f"{note['author_email']} · {note['created_at']}")
                if _can_edit(role) and not note["resolved"]:
                    if st.button("Resolve", key=f"resolve_note_{note['id']}"):
                        try:
                            jobs.resolve_review_note(note["id"], by=user)
                        except jobs.JobError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
    else:
        st.caption("No review notes yet.")

    if _can_edit(role):
        anchor_kind = st.selectbox(
            "Note anchor",
            ["job", "record", "control_number", "validation_issue", "field"],
            key=f"note_anchor_kind_{job_id}",
        )
        anchor_value = st.text_input(
            "Anchor value",
            key=f"note_anchor_value_{job_id}",
            placeholder="Record number, 001/OCLC, issue id, or field",
        )
        note_text = st.text_area("Note", key=f"note_text_{job_id}")
        if st.button("Add note", key=f"add_note_{job_id}"):
            try:
                jobs.add_review_note(
                    job_id,
                    anchor_kind=anchor_kind,
                    anchor_value=anchor_value,
                    note=note_text,
                    author=user,
                )
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.rerun()

    st.subheader("Activity")
    activity = jobs.list_activity(job_id, user_email=user)
    if activity:
        for row in reversed(activity[-20:]):
            st.write(f"{row['created_at']} — {row['actor_email']}: {row['message']}")
    else:
        st.caption("No activity recorded yet.")

    if _can_manage(role):
        st.subheader("Archive")
        if job["active"]:
            if st.button("Archive job", key=f"archive_job_{job_id}"):
                try:
                    jobs.archive_job(job_id, by=user)
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop("selected_job_detail_id", None)
                    st.rerun()
        else:
            if st.button("Restore job", key=f"restore_job_{job_id}"):
                try:
                    jobs.restore_job(job_id, by=user)
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()


def _render() -> None:
    session.init_page()
    user = session.current_user_id()
    if is_anonymous(user):
        st.info("Sign in to use shared job workspaces.")
        return
    job_id = st.session_state.get("selected_job_detail_id")
    if job_id:
        _render_detail(user, int(job_id))
    else:
        _render_list(user)


if __name__ == "__main__":
    _render()
