"""Private Operations console for durable saved-task runs (TASK-156)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from marcedit_web.lib import job_files, operation_results, operations, session


_ACTIVE_STATES = {"queued", "running", "cancelling"}
_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_STATUS_SIGNATURE_KEY = "operations_status_signature"
_WORKER_UNAVAILABLE = (
    "Processing service unavailable. Your operation is safely queued and "
    "will start when the worker returns."
)


def render() -> None:
    """Render counts, live status, and retained operation history."""
    user = session.current_user_id().strip().lower()
    rows = operations.list_visible_operations(user)
    st.session_state[_STATUS_SIGNATURE_KEY] = _status_signature(rows)
    _render_counts(rows)
    if not rows:
        st.info(
            "No operations yet. Saved-task runs will appear here after they "
            "are queued."
        )
        return

    active = [row for row in rows if row["state"] in _ACTIVE_STATES]
    if active:
        st.subheader("Active")
        fragment = getattr(st, "fragment", None)
        if callable(fragment):
            fragment(run_every="2s")(_render_active_for_user)(user)
        else:
            if st.button(
                "Refresh", key="operations_refresh", icon=":material/refresh:"
            ):
                st.rerun()
            _render_active_rows(active, user, operations.worker_health())

    terminal = [row for row in rows if row["state"] in _TERMINAL_STATES]
    if terminal:
        st.subheader("History")
        for row in terminal:
            _render_terminal(row, user)


def _render_active_for_user(user: str) -> None:
    rows = operations.list_visible_operations(user)
    if _status_signature(rows) != st.session_state.get(_STATUS_SIGNATURE_KEY):
        _request_full_rerun()
        return
    active = [row for row in rows if row["state"] in _ACTIVE_STATES]
    _render_active_rows(active, user, operations.worker_health())


def _render_counts(rows: list[dict[str, Any]]) -> None:
    counts = {
        "Running": sum(row["state"] in {"running", "cancelling"} for row in rows),
        "Queued": sum(row["state"] == "queued" for row in rows),
        "Needs attention": sum(
            row["state"] == "failed"
            or (row["state"] == "completed" and int(row["error_count"]) > 0)
            for row in rows
        ),
        "Completed": sum(
            row["state"] == "completed" and int(row["error_count"]) == 0
            for row in rows
        ),
    }
    for column, (label, value) in zip(st.columns(4), counts.items()):
        column.metric(label, str(value))


def _render_active_rows(
    rows: list[dict[str, Any]],
    user: str,
    health: dict[str, Any],
) -> None:
    for row in rows:
        operation_id = int(row["id"])
        with st.container(border=True):
            st.text(
                f"{_operation_name(row)}\n"
                f"{_status_label(row)} · Operation {operation_id}"
            )
            st.text(
                f"{row['source_label']} · Submitted by {row['submitted_by']} · "
                f"{_task_names_label(row)}"
            )
            processed = int(row["processed_records"])
            total = int(row["total_records"])
            fraction = min(processed / total, 1.0) if total else 0.0
            st.progress(
                fraction,
                text=(
                    f"{processed:,} of {total:,} records · {fraction:.0%} · "
                    f"{_phase(row)}"
                ),
            )
            st.caption(f"Elapsed: {_elapsed(row)}")
            if row["state"] == "queued" and not health["available"]:
                st.warning(_WORKER_UNAVAILABLE)
            if row.get("can_cancel") and st.button(
                "Cancel",
                key=f"operation_cancel_{operation_id}",
                icon=":material/cancel:",
            ):
                _run_action(
                    operations.request_cancel,
                    operation_id,
                    by=user,
                )


def _render_terminal(row: dict[str, Any], user: str) -> None:
    operation_id = int(row["id"])
    label = f"{_status_label(row)} · Operation {operation_id}"
    with st.expander(label):
        st.text(_operation_name(row))
        st.text(
            f"{row['source_label']} · Submitted by {row['submitted_by']} · "
            f"{_task_names_label(row)}"
        )
        st.caption(
            f"Submitted {row['submitted_at']} · Completed "
            f"{row.get('completed_at') or 'time unavailable'} · "
            f"Elapsed {_elapsed(row)}"
        )
        _render_terminal_summary(row)
        _render_errors_and_events(row, user)
        if row.get("artifacts_expire_at"):
            st.caption(f"Retained until {row['artifacts_expire_at']}")
        if row["state"] == "completed":
            _render_result_actions(row, user)


def _render_terminal_summary(row: dict[str, Any]) -> None:
    if row["terminal_message"]:
        st.write(row["terminal_message"])
    if row["state"] == "completed":
        st.write(
            f"{int(row['output_records'] or 0):,} records out · "
            f"{int(row['changed_records'] or 0):,} changed · "
            f"{int(row['error_count']):,} record errors"
        )
    summary = row.get("summary", {})
    if summary:
        safe_summary = {
            key: value
            for key, value in summary.items()
            if key in {"input_records", "output_records", "changed_records", "error_count"}
        }
        if safe_summary:
            st.caption(
                "Summary: "
                + " · ".join(
                    f"{key.replace('_', ' ')} {value:,}"
                    if isinstance(value, int) else f"{key.replace('_', ' ')} {value}"
                    for key, value in safe_summary.items()
                )
            )


def _render_errors_and_events(row: dict[str, Any], user: str) -> None:
    operation_id = int(row["id"])
    try:
        retained_errors = operations.list_errors(operation_id, user)
        events = operations.list_events(operation_id, user)
    except operations.OperationError as exc:
        st.error(str(exc))
        return
    if int(row["error_count"]):
        st.markdown("**Record errors**")
        st.caption(
            f"Showing {len(retained_errors):,} of {int(row['error_count']):,}"
        )
        for error in retained_errors:
            task = f" · {error['task_name']}" if error.get("task_name") else ""
            st.write(
                f"Record {int(error['record_index']):,}{task}: {error['message']}"
            )
    if events:
        st.markdown("**Activity**")
        for event in events:
            st.write(
                f"{event['created_at']} · {event['message']} · "
                f"{event['actor_email']}"
            )


def _render_result_actions(row: dict[str, Any], user: str) -> None:
    operation_id = int(row["id"])
    st.markdown("**Result review**")
    if not row.get("can_access_artifacts"):
        st.caption("Result actions require current access to the source file.")
        return
    try:
        artifacts = operations.list_artifacts(operation_id, user)
    except operations.OperationError as exc:
        st.error(str(exc))
        return
    result = next((item for item in reversed(artifacts) if item["role"] == "result"), None)
    result_available = result is not None and _artifact_available(result, row)
    if result_available:
        if st.button(
            "Prepare result download",
            key=f"operation_prepare_download_{operation_id}",
            icon=":material/download:",
        ):
            try:
                data = Path(result["file_path"]).read_bytes()
            except OSError:
                st.error("The retained result is no longer available.")
            else:
                st.download_button(
                    "Download result",
                    data=data,
                    file_name=str(result["filename"]),
                    mime="application/marc",
                    key=f"operation_download_{operation_id}",
                )
    else:
        st.caption("The retained result expired or is no longer available.")

    if row["job_id"] is not None:
        _render_job_actions(row, user, result_available)
    else:
        _render_quick_load_actions(row, user, result_available, artifacts)


def _render_job_actions(
    row: dict[str, Any], user: str, result_available: bool
) -> None:
    operation_id = int(row["id"])
    opened_version = st.session_state.get("job_file_version_id")
    if row.get("can_apply_result"):
        if result_available and st.button(
            "Apply as new Job version",
            key=f"operation_apply_{operation_id}",
            icon=":material/publish:",
        ):
            if opened_version is None:
                st.error("Open the source Job file version before applying.")
            else:
                _run_action(
                    operation_results.apply_job_result,
                    operation_id,
                    user_email=user,
                    opened_version_id=int(opened_version),
                )
    elif row.get("can_rollback_result"):
        st.success(f"Applied as Job version {row['applied_version_id']}.")
        if st.button(
            "Roll back as a new Job version",
            key=f"operation_rollback_{operation_id}",
            icon=":material/restore:",
        ):
            if opened_version is None:
                st.error("Open the applied Job file version before rolling back.")
            else:
                _run_action(
                    operation_results.rollback_job_result,
                    operation_id,
                    user_email=user,
                    opened_version_id=int(opened_version),
                )
    elif row.get("rolled_back_version_id") is not None:
        st.caption(f"Rolled back as Job version {row['rolled_back_version_id']}.")
    elif row.get("applied_version_id") is not None:
        st.caption(f"Applied as Job version {row['applied_version_id']}.")


def _render_quick_load_actions(
    row: dict[str, Any],
    user: str,
    result_available: bool,
    artifacts: list[dict[str, Any]],
) -> None:
    operation_id = int(row["id"])
    if result_available and st.button(
        "Open result in Quick Load",
        key=f"operation_reopen_result_{operation_id}",
        icon=":material/file_open:",
    ):
        _run_action(
            operation_results.reopen_quick_load,
            operation_id,
            user_email=user,
            use_result=True,
        )
    original = next((item for item in artifacts if item["role"] == "input"), None)
    if original is not None and _artifact_available(original, row) and st.button(
        "Reopen original in Quick Load",
        key=f"operation_reopen_input_{operation_id}",
        icon=":material/undo:",
    ):
        _run_action(
            operation_results.reopen_quick_load,
            operation_id,
            user_email=user,
            use_result=False,
        )


def _run_action(function, operation_id: int, **kwargs: Any) -> None:
    try:
        function(operation_id, **kwargs)
    except (operations.OperationError, job_files.JobFileError) as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _operation_name(row: dict[str, Any]) -> str:
    tasks = row.get("task_names", [])
    return tasks[0] if len(tasks) == 1 else "Saved-task run"


def _task_names_label(row: dict[str, Any]) -> str:
    tasks = row.get("task_names", [])
    return "Tasks: " + " → ".join(tasks) if tasks else "Saved tasks"


def _status_signature(rows: list[dict[str, Any]]) -> tuple[tuple[int, str], ...]:
    return tuple(sorted((int(row["id"]), str(row["state"])) for row in rows))


def _request_full_rerun() -> None:
    rerun = getattr(st, "rerun", None)
    if not callable(rerun):
        rerun = getattr(st, "experimental_rerun", None)
    if callable(rerun):
        rerun()


def _status_label(row: dict[str, Any]) -> str:
    state = str(row["state"])
    if state == "completed" and int(row["error_count"]) > 0:
        return "Completed with errors"
    return state.replace("_", " ").capitalize()


def _phase(row: dict[str, Any]) -> str:
    return str(row["phase"]).replace("_", " ").capitalize()


def _elapsed(row: dict[str, Any]) -> str:
    start = _parse_time(row.get("started_at") or row.get("submitted_at"))
    end = _parse_time(row.get("completed_at")) or datetime.now(timezone.utc)
    if start is None:
        return "Not available"
    seconds = max(int((end - start).total_seconds()), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _artifact_available(
    artifact: dict[str, Any], row: dict[str, Any]
) -> bool:
    expires = _parse_time(
        artifact.get("expires_at") or row.get("artifacts_expire_at")
    )
    if expires is not None and expires <= datetime.now(timezone.utc):
        return False
    return Path(artifact["file_path"]).is_file()
