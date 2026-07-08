"""Jobs workspace page (TASK-118)."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import jobs, session
from marcedit_web.lib.identity import is_anonymous


def _status_label(status: str) -> str:
    return status.replace("_", " ").capitalize()


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
    job = jobs.get_job(job_id)
    if job is None:
        st.error("Job not found.")
        return
    role = jobs.get_access_role(job_id, user)
    if role is None:
        st.error("You do not have access to this job.")
        return

    if st.button("Back to jobs", key="jobs_back"):
        st.session_state.pop("selected_job_detail_id", None)
        st.rerun()
    st.title(job["name"])
    st.caption(f"{_status_label(job['status'])} · {role} · owned by {job['owner_email']}")

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

    st.subheader("Activity")
    activity = jobs.list_activity(job_id, user_email=user)
    if activity:
        for row in reversed(activity[-20:]):
            st.write(f"{row['created_at']} — {row['actor_email']}: {row['message']}")
    else:
        st.caption("No activity recorded yet.")


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
