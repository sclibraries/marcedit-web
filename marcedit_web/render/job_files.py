"""Shared job-file attachment and table UI (TASK-151).

One renderer keeps Home's Job Workspace and the Jobs detail page on the
same attachment, open, and archive paths.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from marcedit_web.lib import collaboration, db, job_files, locks, session

# One line per file; weights keep Open and the ⋮ trigger from wrapping.
UPLOADS_GRID = [3, 1.5, 1, 1, 2, 2, 1, 1.5, 0.6]
UPLOADS_HEADERS = (
    "Name", "Status", "Version", "Records", "Last editor", "Updated", "", "", ""
)

_EDIT_ROLES = {"owner", "editor"}
_OPENED_VERSIONS_KEY = "job_file_opened_versions"


def render_file_exports(
    file_row: dict,
    *,
    user: str,
    opened_version_id: int | None,
) -> None:
    """Render retained labeled exports and their manual load audit controls."""
    st = _streamlit()
    file_id = int(file_row["id"])
    can_edit = file_row.get("access_role") in _EDIT_ROLES
    st.markdown("**Exports**")
    st.caption(
        "Exports are retained copies of one exact file version. Marking one "
        "loaded records the external load; it does not complete this file."
    )

    if can_edit:
        purpose = st.text_input("Purpose", key=f"file_export_purpose_{file_id}")
        description = st.text_area(
            "Description (optional)", key=f"file_export_description_{file_id}"
        )
        filename = st.text_input(
            "Filename (optional)", key=f"file_export_filename_{file_id}"
        )
        if st.button("Create export", key=f"file_export_create_{file_id}"):
            if opened_version_id is None:
                st.error("Reopen this file before creating an export.")
            else:
                try:
                    created = job_files.create_export(
                        file_id=file_id,
                        opened_version_id=int(opened_version_id),
                        user_email=user,
                        purpose=purpose,
                        description=description,
                        filename=filename or None,
                    )
                except job_files.JobFileError as exc:
                    st.error(str(exc))
                else:
                    st.success(
                        f"Created {created['state']} export: {created['purpose']}."
                    )
                    st.rerun()

    exports = job_files.list_exports(file_id, user)
    if not exports:
        st.caption("No retained exports yet.")
        return
    for export in exports:
        _render_file_export(export, user=user, can_edit=can_edit)


def _render_file_export(export: dict, *, user: str, can_edit: bool) -> None:
    st = _streamlit()
    export_id = int(export["id"])
    state = str(export["state"]).capitalize()
    st.markdown(
        f"**{export['purpose']}** — {state} · v{export['version_number']}"
    )
    if export.get("description"):
        st.caption(export["description"])
    st.caption(
        f"{export['filename']} · {int(export['record_count']):,} records · "
        f"created by {export['created_by']} at {export['created_at']}"
    )
    if export["state"] == "loaded":
        details = (
            f"Loaded to {export['loaded_destination']} by {export['loaded_by']} "
            f"at {export['loaded_at']}"
        )
        if export.get("loaded_external_id"):
            details += f" · external id {export['loaded_external_id']}"
        st.caption(details)
        if export.get("loaded_note"):
            st.caption(export["loaded_note"])

    path = Path(export["file_path"])
    ready_key = f"file_export_download_ready_{export_id}"
    if not path.is_file():
        st.caption("Retained export file is unavailable.")
    elif not st.session_state.get(ready_key):
        if st.button(
            "Prepare download",
            key=f"file_export_prepare_{export_id}",
            help="Loads this retained export from disk for download.",
        ):
            st.session_state[ready_key] = True
            st.rerun()
    else:
        st.download_button(
            label="Download retained export",
            data=path.read_bytes(),
            file_name=export["filename"],
            mime="application/marc",
            key=f"file_export_download_{export_id}",
        )

    if export["state"] != "ready" or not can_edit:
        return
    destination = st.text_input(
        "Loaded destination",
        key=f"file_export_destination_{export_id}",
    )
    external_id = st.text_input(
        "External id (optional)",
        key=f"file_export_external_id_{export_id}",
    )
    note = st.text_area(
        "Load note (optional)",
        key=f"file_export_note_{export_id}",
    )
    if st.button("Mark loaded", key=f"file_export_loaded_{export_id}"):
        try:
            job_files.mark_export_loaded(
                export_id,
                by=user,
                destination=destination,
                external_id=external_id,
                note=note,
            )
        except job_files.JobFileError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def _streamlit():
    if "st" in globals():
        return globals()["st"]
    import streamlit

    return streamlit


def _checkout_actions(
    role: str | None,
    holder_email: str | None,
    user: str,
) -> tuple[str, ...]:
    if role not in _EDIT_ROLES:
        return ()
    if holder_email is None:
        return ("Check out",)
    if holder_email == user:
        return ("Renew", "Done", "Return for review")
    if role == "owner":
        return ("Force release",)
    return ()


def _checkout_label(checkout: dict | None) -> str:
    if checkout is None:
        return "Available for checkout"
    return (
        f"Checked out by {checkout['holder_email']} until "
        f"{checkout['expires_at']}"
    )


def _active_checkout(file_id: int) -> dict | None:
    db.init_schema()
    checkout = locks.get_lock("job-file", str(file_id))
    if checkout is None:
        return None
    expires_at = dt.datetime.fromisoformat(
        checkout["expires_at"].removesuffix("Z")
    )
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return checkout if expires_at > now else None


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
            checkout = _active_checkout(int(row["id"]))
            holder_email = checkout["holder_email"] if checkout else None
            cols = st.columns(
                UPLOADS_GRID, vertical_alignment="center", gap="small"
            )
            cols[0].write(row["display_name"])
            cols[0].write(_checkout_label(checkout))
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
                    _remember_opened_version(st, row, summary)
                    total = int(summary.get("total", 0))
                    session.queue_toast(
                        f"Opened {row['display_name']} — {total:,} "
                        f"record{'s' if total != 1 else ''}",
                        icon="📂",
                    )
                    st.switch_page("views/1_View.py")
            if cols[7].button(
                "History & review",
                key=f"{key_prefix}_history_{row['id']}",
                use_container_width=True,
            ):
                try:
                    summary = session.open_job_file(int(row["id"]))
                except job_files.JobFileError as exc:
                    st.error(str(exc))
                else:
                    _remember_opened_version(st, row, summary)
                    st.switch_page("views/C_History.py")
            actions = _checkout_actions(role, holder_email, user)
            opened_version_id = _opened_version_id(st, int(row["id"]))
            if opened_version_id is None or row["status"] != "in_progress":
                actions = tuple(
                    action for action in actions if action != "Return for review"
                )
            if role not in _EDIT_ROLES:
                continue
            with cols[8].popover("⋮"):
                if "Check out" in actions and st.button(
                    "Check out",
                    key=f"{key_prefix}_checkout_{row['id']}",
                    use_container_width=True,
                ):
                    _acquire_checkout(st, row, user)
                if "Renew" in actions and st.button(
                    "Renew",
                    key=f"{key_prefix}_renew_{row['id']}",
                    use_container_width=True,
                ):
                    _acquire_checkout(st, row, user)
                if "Done" in actions and st.button(
                    "Done",
                    key=f"{key_prefix}_done_{row['id']}",
                    use_container_width=True,
                ):
                    collaboration.release_file_checkout(int(row["id"]), user)
                    _forget_opened_version(st, int(row["id"]))
                    st.rerun()
                if "Return for review" in actions and st.button(
                    "Return for review",
                    key=f"{key_prefix}_review_{row['id']}",
                    use_container_width=True,
                ):
                    try:
                        job_files.return_for_review(
                            int(row["id"]),
                            by=user,
                            opened_version_id=int(opened_version_id),
                        )
                    except job_files.JobFileError as exc:
                        st.error(str(exc))
                    else:
                        _forget_opened_version(st, int(row["id"]))
                        st.rerun()
                if "Force release" in actions:
                    _render_force_release(st, row, user, key_prefix)
                if holder_email == user and opened_version_id is not None:
                    if st.button(
                        "Remove from job",
                        key=f"{key_prefix}_remove_{row['id']}",
                        use_container_width=True,
                    ):
                        try:
                            job_files.archive_file(
                                int(row["id"]),
                                by=user,
                                opened_version_id=int(opened_version_id),
                            )
                        except job_files.JobFileError as exc:
                            st.error(str(exc))
                        else:
                            _forget_opened_version(st, int(row["id"]))
                            session.queue_toast(
                                f"Archived {row['display_name']}.",
                                icon="🗂️",
                            )
                            st.rerun()
                    st.caption(
                        "Keeps every version and export; hides this file."
                    )


def _acquire_checkout(st, row: dict, user: str) -> None:
    file_id = int(row["id"])
    active_checkout = _active_checkout(file_id)
    preserve_opened_version = (
        active_checkout is not None
        and active_checkout["holder_email"] == user
        and _opened_version_id(st, file_id) is not None
    )
    try:
        decision = collaboration.acquire_file_checkout(file_id, user)
    except collaboration.CollaborationError as exc:
        st.error(str(exc))
        return
    if not decision.acquired:
        st.error(
            f"Checked out by {decision.holder_email} until {decision.expires_at}."
        )
        return
    if preserve_opened_version:
        st.rerun()
        return
    try:
        version = job_files.get_current_version(file_id, user)
    except job_files.JobFileError as exc:
        st.error(str(exc))
        return
    _set_opened_version(st, file_id, int(version["id"]))
    st.rerun()


def _remember_opened_version(st, row: dict, summary: dict) -> None:
    version_id = summary.get("job_file_version_id")
    if version_id is not None:
        _set_opened_version(st, int(row["id"]), int(version_id))


def _set_opened_version(st, file_id: int, version_id: int) -> None:
    versions = dict(st.session_state.get(_OPENED_VERSIONS_KEY, {}))
    versions[str(file_id)] = version_id
    st.session_state[_OPENED_VERSIONS_KEY] = versions


def _opened_version_id(st, file_id: int) -> int | None:
    value = st.session_state.get(_OPENED_VERSIONS_KEY, {}).get(str(file_id))
    return int(value) if value is not None else None


def _forget_opened_version(st, file_id: int) -> None:
    versions = dict(st.session_state.get(_OPENED_VERSIONS_KEY, {}))
    versions.pop(str(file_id), None)
    st.session_state[_OPENED_VERSIONS_KEY] = versions


def _render_force_release(st, row: dict, user: str, key_prefix: str) -> None:
    confirm_key = f"{key_prefix}_force_release_confirm_{row['id']}"
    if not st.session_state.get(confirm_key):
        if st.button(
            "Force release",
            key=f"{key_prefix}_force_release_{row['id']}",
            use_container_width=True,
        ):
            st.session_state[confirm_key] = True
            st.rerun()
        return
    st.warning("Force release this cataloger's checkout?")
    if st.button(
        "Confirm force release",
        key=f"{key_prefix}_force_release_confirm_button_{row['id']}",
        use_container_width=True,
    ):
        try:
            collaboration.force_release_file_checkout(int(row["id"]), by=user)
        except collaboration.CollaborationError as exc:
            st.error(str(exc))
        else:
            st.session_state.pop(confirm_key, None)
            st.rerun()
    if st.button(
        "Cancel",
        key=f"{key_prefix}_force_release_cancel_{row['id']}",
        use_container_width=True,
    ):
        st.session_state.pop(confirm_key, None)
        st.rerun()


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
