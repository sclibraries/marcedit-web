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

from marcedit_web.lib import jobs, session
from marcedit_web.lib.identity import is_anonymous

session.init_page()


def _job_label(job: dict) -> str:
    role = job.get("access_role")
    if role and role != "owner":
        return f"{job['name']} ({role})"
    return job["name"]


# --- Upload widget (handled FIRST so the sidebar reads fresh state) --------


st.title("marcedit-web")
st.caption("MARC21 viewer, validator, editor, and diff — in your browser.")
# h2 — heading ladder must step h1 → h2 → h3 without gaps (TASK-054).
st.header("Upload a MARC file")

user = session.current_user_id()
if not is_anonymous(user):
    job_rows = jobs.list_jobs(user)
    if not job_rows:
        job_rows = [jobs.ensure_default_job(user)]

    current_job_id = st.session_state.get("current_job_id")
    job_ids = [job["id"] for job in job_rows]
    if current_job_id not in job_ids:
        current_job_id = job_ids[0]
        st.session_state["current_job_id"] = current_job_id

    selected_job_id = st.selectbox(
        "Job",
        options=job_ids,
        index=job_ids.index(current_job_id),
        format_func=lambda job_id: next(
            _job_label(job) for job in job_rows if job["id"] == job_id
        ),
        help="Uploads attach to the selected job.",
        key="current_job_id",
    )
    current_job_id = int(selected_job_id)

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
                st.session_state["current_job_id"] = created["id"]
                st.success(f"Created job `{created['name']}`.")
                st.rerun()

    role = jobs.get_access_role(current_job_id, user)
    if role == "owner":
        with st.expander("Share job", expanded=False):
            share_email = st.text_input(
                "Cataloger email",
                placeholder="name@example.edu",
                key="share_job_email",
            )
            share_role = st.selectbox(
                "Role",
                ["editor", "viewer"],
                key="share_job_role",
            )
            if st.button("Grant access", key="share_job_grant"):
                try:
                    jobs.grant_access(
                        current_job_id,
                        share_email,
                        share_role,
                        by=user,
                    )
                except jobs.JobError as exc:
                    st.error(str(exc))
                else:
                    st.success("Access granted.")
                    st.rerun()

            access_rows = jobs.list_access(current_job_id)
            st.dataframe(access_rows, hide_index=True, use_container_width=True)

            revoke_options = [
                row["user_email"] for row in access_rows
                if row["role"] != "owner"
            ]
            if revoke_options:
                revoke_email = st.selectbox(
                    "Remove access",
                    revoke_options,
                    key="share_job_revoke_email",
                )
                if st.button("Revoke access", key="share_job_revoke"):
                    try:
                        jobs.revoke_access(
                            current_job_id,
                            revoke_email,
                            by=user,
                        )
                    except jobs.JobError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Access revoked.")
                        st.rerun()

uploaded = st.file_uploader(
    "Choose a .mrc file",
    type=["mrc", "marc"],
    accept_multiple_files=False,
    help=(
        "Binary MARC21. Upload limit is set in `.streamlit/config.toml` "
        "(currently 2 GB). Large files may take a moment to parse."
    ),
)

upload_summary = None
if uploaded is not None:
    # Parsing a large .mrc can take several seconds; without a spinner
    # the page appears frozen and the cataloger doesn't know whether
    # to wait or refresh.
    with st.spinner(f"Parsing {uploaded.name}…"):
        upload_summary = session.handle_upload(uploaded)
    if upload_summary.get("error"):
        st.error(
            f"Upload rejected: {upload_summary['error']}. Contact ops if "
            "you need a higher limit for this batch."
        )


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


# --- Inline upload feedback ------------------------------------------------


if upload_summary is not None and not upload_summary.get("error"):
    if upload_summary["total"] == 0 and upload_summary["malformed"] == 0:
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

    st.divider()
    st.markdown(
        "**Next steps:** pick a page from the sidebar — **Inspect** for "
        "viewing / validation / reports, **Edit** for the .mrk editor "
        "and Tasks transforms, **Reconcile** for Diff / Dedupe / format "
        "conversion."
    )
else:
    st.info(
        "Upload a `.mrc` file above to begin. Nothing persists across "
        "sessions — closing the tab discards everything."
    )
