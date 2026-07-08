"""marcedit-web — landing page.

The cataloger uploads a `.mrc` file here. We parse it once on upload and
hold the parsed records in `st.session_state` so every other page reads
from the same in-memory source. Closing the tab discards everything.

TASK-045: this used to live at ``marcedit_web/Home.py`` (the Docker
entrypoint). It moved here when the entrypoint became a pure
``st.navigation`` host. ``st.set_page_config`` lives in the entrypoint
now — only one call per render is allowed.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from marcedit_web.lib import jobs, session
from marcedit_web.lib.identity import is_anonymous

session.init_page()

_PENDING_CURRENT_JOB_ID = "pending_current_job_id"
_START_PATH_KEY = "home_start_path"
_START_PATH_QUERY_KEY = "start"
_START_PATH_QUICK = "Quick Load"
_START_PATH_JOB = "Job Workspace"
_START_PATH_TO_QUERY = {
    _START_PATH_QUICK: "quick",
    _START_PATH_JOB: "jobs",
}
_QUERY_TO_START_PATH = {value: key for key, value in _START_PATH_TO_QUERY.items()}

# One line per file: Filename | Records | Uploaded | Status | Load | ⋮.
# Weights tuned so "Load" and the ⋮ trigger never wrap (TASK-126).
_UPLOADS_GRID = [4, 1, 2, 1.4, 1, 0.6]
_UPLOADS_HEADERS = ("Filename", "Records", "Uploaded", "Status", "", "")


def _job_label(job: dict) -> str:
    role = job.get("access_role")
    if role and role != "owner":
        return f"{job['name']} ({role})"
    return job["name"]


def _can_edit_job(role: str | None) -> bool:
    return role in {"owner", "editor"}


def _set_current_job(job_id: int) -> None:
    st.session_state["current_job_id"] = job_id


def _apply_pending_job(job_ids: list[int]) -> int:
    pending_job_id = st.session_state.pop(_PENDING_CURRENT_JOB_ID, None)
    current_job_id = pending_job_id or st.session_state.get("current_job_id")
    if current_job_id not in job_ids:
        current_job_id = job_ids[0]
        _set_current_job(current_job_id)
    elif pending_job_id is not None:
        _set_current_job(current_job_id)
    return int(current_job_id)


def _activate_quick_load(default_job_id: int | None) -> None:
    st.session_state["quick_load_mode"] = True
    if default_job_id is not None:
        _set_current_job(default_job_id)


def _query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _default_start_path() -> str:
    query_path = _QUERY_TO_START_PATH.get(_query_param(_START_PATH_QUERY_KEY))
    if query_path is not None:
        return query_path
    if st.session_state.get("quick_load_mode"):
        return _START_PATH_QUICK
    return _START_PATH_QUICK


def _sync_start_path_query() -> None:
    path = st.session_state.get(_START_PATH_KEY, _START_PATH_QUICK)
    st.query_params[_START_PATH_QUERY_KEY] = _START_PATH_TO_QUERY[path]


def _handle_uploaded_file(uploaded_file):
    # Parsing a large .mrc can take several seconds; without a spinner
    # the page appears frozen and the cataloger doesn't know whether
    # to wait or refresh.
    with st.spinner(f"Parsing {uploaded_file.name}…"):
        return session.handle_upload(uploaded_file)


def _render_next_actions() -> None:
    st.write("Next actions")
    cols = st.columns(5)
    if cols[0].button("View records", key="next_view"):
        st.switch_page("views/1_View.py")
    if cols[1].button("Validate", key="next_validate"):
        st.switch_page("views/2_Validate.py")
    if cols[2].button("Report", key="next_report"):
        st.switch_page("views/3_Report.py")
    if cols[3].button("Edit", key="next_edit"):
        st.switch_page("views/5_MarcEditor.py")
    if cols[4].button("Tools", key="next_tools"):
        st.switch_page("views/9_MarcTools.py")


def _render_upload_feedback(upload_summary: dict) -> None:
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
        _render_next_actions()


def _format_uploaded_at(value) -> str:
    # uploads.uploaded_at is ISO-8601 UTC ("2026-07-01T09:14:32Z");
    # catalogers scan dates, so render "Jul 1, 2026 09:14" instead.
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.strftime('%Y %H:%M')}"


def _render_job_uploads(job_id: int, user: str, role: str | None) -> None:
    uploads = jobs.list_job_uploads(job_id)
    st.subheader("Files in this job")
    if not uploads:
        st.caption("No MARC files have been added to this job yet.")
        return
    with st.container(border=True):
        headers = st.columns(
            _UPLOADS_GRID, vertical_alignment="center", gap="small"
        )
        for col, title in zip(headers, _UPLOADS_HEADERS):
            if title:
                col.markdown(f"**{title}**")
        st.divider()
        for row in uploads:
            cols = st.columns(
                _UPLOADS_GRID, vertical_alignment="center", gap="small"
            )
            cols[0].write(row["filename"])
            cols[1].write(f"{row['record_count']:,}")
            cols[2].write(_format_uploaded_at(row["uploaded_at"]))
            cols[3].markdown(
                ":green[● Current]" if row["active"] else ":gray[Available]"
            )
            if cols[4].button(
                "Load",
                key=f"home_job_upload_load_{row['id']}",
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
            can_remove = _can_edit_job(role)
            can_delete = row["user_email"] == user
            if not (can_remove or can_delete):
                continue
            with cols[5].popover("⋮"):
                if can_remove:
                    if st.button(
                        "Remove from job",
                        key=f"home_job_upload_remove_{row['id']}",
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
                        key=f"home_job_upload_delete_{row['id']}",
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
                            st.rerun()
                    st.caption("Deletes the stored file for everyone in the job.")


# --- Upload widget (handled FIRST so the sidebar reads fresh state) --------


st.title("marcedit-web")
st.caption("MARC21 viewer, validator, editor, and diff — in your browser.")
# h2 — heading ladder must step h1 → h2 → h3 without gaps (TASK-054).
st.header("Upload a MARC file")

user = session.current_user_id()
default_job = None
job_rows: list[dict] = []
if not is_anonymous(user):
    default_job = jobs.ensure_default_job(user)
    job_rows = jobs.list_jobs(user)
    job_ids = [job["id"] for job in job_rows]
    if default_job["id"] not in job_ids:
        job_rows = [default_job, *job_rows]

start_path = st.radio(
    "Start path",
    [_START_PATH_QUICK, _START_PATH_JOB],
    index=[_START_PATH_QUICK, _START_PATH_JOB].index(_default_start_path()),
    horizontal=True,
    key=_START_PATH_KEY,
    on_change=_sync_start_path_query,
)
_sync_start_path_query()

upload_summary = None
if start_path == _START_PATH_QUICK:
    st.subheader("Quick Load")
    st.caption("Use this for one-off viewing, validation, reports, editing, or conversion.")
    if default_job is not None and st.session_state.get("quick_load_mode"):
        _set_current_job(default_job["id"])

    uploaded = st.file_uploader(
        "Choose a .mrc file",
        type=["mrc", "marc"],
        accept_multiple_files=False,
        help=(
            "Binary MARC21. Upload limit is set in `.streamlit/config.toml` "
            "(currently 2 GB). Large files may take a moment to parse."
        ),
        key="home_quick_load_upload",
        on_change=(
            None
            if default_job is None
            else lambda: _activate_quick_load(int(default_job["id"]))
        ),
    )
    if uploaded is not None:
        upload_summary = _handle_uploaded_file(uploaded)
        _render_upload_feedback(upload_summary)

if start_path == _START_PATH_JOB:
    st.subheader("Job Workspace")
    st.caption("Use jobs for shared vendor loads, review, and handoff.")
    if is_anonymous(user):
        st.info("Sign in to create or continue shared jobs.")
    else:
        job_ids = [job["id"] for job in job_rows]
        current_job_id = _apply_pending_job(job_ids)
        selected_job_id = st.selectbox(
            "Job",
            options=job_ids,
            index=job_ids.index(current_job_id),
            format_func=lambda job_id: next(
                _job_label(job) for job in job_rows if job["id"] == job_id
            ),
            help="Use the Jobs page for sharing, review, and handoff details.",
            key="current_job_id",
        )
        current_job_id = int(selected_job_id)
        st.session_state["quick_load_mode"] = False

        with st.expander("Create job", expanded=False):
            new_job_name = st.text_input(
                "Job name",
                placeholder="e.g. Vendor load June",
                key="new_job_name",
            )
            if st.button("Create job", key="create_job_btn"):
                try:
                    created = jobs.create_job(user, new_job_name)
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    st.session_state[_PENDING_CURRENT_JOB_ID] = created["id"]
                    st.rerun()

        job_upload = st.file_uploader(
            "Add a .mrc file to this job",
            type=["mrc", "marc"],
            accept_multiple_files=False,
            help=(
                "Uploads here attach to the selected job and appear in that "
                "job's Files list."
            ),
            key="home_job_workspace_upload",
        )
        if job_upload is not None:
            upload_summary = _handle_uploaded_file(job_upload)
            _render_upload_feedback(upload_summary)

        current_job = next(job for job in job_rows if job["id"] == current_job_id)
        current_role = current_job.get("access_role")
        if current_role is None and current_job.get("owner_email") == user:
            current_role = "owner"
        _render_job_uploads(
            current_job_id,
            user,
            current_role,
        )

        summaries = jobs.list_job_summaries(user)
        for row in summaries[:5]:
            cols = st.columns([4, 2, 1])
            cols[0].write(row["name"])
            cols[1].write(row["status"].replace("_", " ").capitalize())
            if cols[2].button("Open", key=f"home_open_job_{row['id']}"):
                st.session_state["selected_job_detail_id"] = row["id"]
                st.switch_page("views/B_Jobs.py")


# --- Sidebar ---------------------------------------------------------------


with st.sidebar:
    st.header("marcedit-web")
    from marcedit_web import __version__
    st.caption(f"v{__version__}")
    user = session.current_user_id()
    st.caption(f"Signed in as **{user}**")
    st.divider()
    if session.has_upload():
        filename = session.current_filename() or "(unnamed)"
        st.caption(f"Loaded: `{filename}`")
        st.caption(f"{session.record_count()} records")
    else:
        st.caption("No file loaded yet.")


# --- Loaded-batch summary + download ---------------------------------------


if session.has_upload():
    st.divider()
    st.header("Loaded batch")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Filename", session.current_filename() or "—")
    col_b.metric("Records", session.record_count())
    store = session.current_store()
    col_c.metric("Malformed", store.malformed_count() if store else 0)

    raw = session.current_raw_bytes()
    if raw is not None:
        st.download_button(
            label="Download current batch (.mrc)",
            data=raw,
            file_name=session.current_filename() or "current.mrc",
            mime="application/marc",
            help=(
                "Returns the current in-session record bytes. Edits from "
                "MarcEditor / Tasks / Quick find/replace are reflected."
            ),
        )

else:
    st.info(
        "Upload a `.mrc` file above to begin. Nothing persists across "
        "sessions — closing the tab discards everything."
    )
