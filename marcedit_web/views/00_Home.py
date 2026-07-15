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

import streamlit as st

from marcedit_web.lib import job_files as work_files, jobs, session
from marcedit_web.lib.identity import is_anonymous
from marcedit_web.render import job_files

session.init_page()

_PENDING_CURRENT_JOB_ID = "pending_current_job_id"
_QUICK_UPLOAD_SUMMARY_KEY = "home_quick_upload_summary"
_QUICK_UPLOAD_NONCE_KEY = "home_quick_upload_nonce"
_START_PATH_KEY = "home_start_path"
_START_PATH_QUERY_KEY = "start"
_START_PATH_QUICK = "Quick Load"
_START_PATH_JOB = "Job Workspace"
_START_PATH_TO_QUERY = {
    _START_PATH_QUICK: "quick",
    _START_PATH_JOB: "jobs",
}
_QUERY_TO_START_PATH = {value: key for key, value in _START_PATH_TO_QUERY.items()}


def _job_label(job: dict) -> str:
    role = job.get("access_role")
    if role and role != "owner":
        return f"{job['name']} ({role})"
    return job["name"]


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
    job_files.render_upload_feedback(upload_summary)
    if not upload_summary.get("error") and upload_summary.get("total"):
        _render_next_actions()


def _finish_upload(upload_summary: dict, nonce_key: str, summary_key: str) -> None:
    """Render errors inline; on success release the uploader widget.

    The widget keeps the full file bytes in server RAM until it is
    cleared, and re-runs re-ingest whatever sits in it (TASK-131,
    memory pattern behind the TASK-117 outage). The batch already
    lives on disk in the RecordStore, so: persist the summary for
    feedback, rotate the widget key (next run remakes it empty), and
    rerun. Rejections AND zero-record files skip rotation — after a
    rotation has_upload() gates the feedback, and an empty store fails
    that gate, so rotating would swallow the "No records found" error.
    """
    if upload_summary.get("error") or not upload_summary.get("total"):
        _render_upload_feedback(upload_summary)
        return
    st.session_state[summary_key] = upload_summary
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1
    st.rerun()


def _render_persisted_upload_feedback(summary_key: str) -> None:
    summary = st.session_state.get(summary_key)
    if not summary or not session.has_upload():
        return
    _render_upload_feedback(summary)


def _render_job_uploads(job_id: int, user: str, role: str | None) -> None:
    files = work_files.list_files(job_id, user)
    st.subheader("Files in this job")
    if not files:
        st.caption("No MARC files have been added to this job yet.")
        return
    job_files.render_job_files_table(
        files,
        user=user,
        role=role,
        key_prefix="home_job_upload",
    )


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
            "Binary MARC21. Upload limit is "
            f"{session.max_upload_bytes() // (1024 * 1024)} MB. "
            "Large files may take a moment to parse."
        ),
        key=(
            "home_quick_load_upload_"
            f"{st.session_state.get(_QUICK_UPLOAD_NONCE_KEY, 0)}"
        ),
        on_change=(
            None
            if default_job is None
            else lambda: _activate_quick_load(int(default_job["id"]))
        ),
    )
    if uploaded is not None:
        upload_summary = _handle_uploaded_file(uploaded)
        _finish_upload(
            upload_summary, _QUICK_UPLOAD_NONCE_KEY, _QUICK_UPLOAD_SUMMARY_KEY
        )
    else:
        _render_persisted_upload_feedback(_QUICK_UPLOAD_SUMMARY_KEY)

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

        current_job = next(job for job in job_rows if job["id"] == current_job_id)
        current_role = current_job.get("access_role")
        if current_role is None and current_job.get("owner_email") == user:
            current_role = "owner"
        job_files.render_attach_file(
            current_job_id,
            user,
            current_role,
            key_prefix="home_job_workspace",
        )
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

    # TASK-135: serializing the batch on every render pins O(file) RAM
    # (the TASK-117 pattern). Build the bytes only on the run where the
    # cataloger asks; Streamlit frees the payload once a later run stops
    # rendering the download button.
    if st.button(
        "Prepare download (.mrc)",
        key="home_prepare_download",
        help=(
            "Serializes the current in-session records. Edits from "
            "MarcEditor / Tasks / Quick find/replace are reflected. "
            "The download link appears next to this button — use it "
            "before interacting elsewhere, or prepare again."
        ),
    ):
        raw = session.current_raw_bytes()
        if raw is not None:
            st.download_button(
                label="Download current batch (.mrc)",
                data=raw,
                file_name=session.current_filename() or "current.mrc",
                mime="application/marc",
            )

else:
    st.info(
        "Upload a `.mrc` file above to begin. Nothing persists across "
        "sessions — closing the tab discards everything."
    )
