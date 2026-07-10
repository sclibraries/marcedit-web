"""Tasks tab — list / create / import / run tasks against the loaded batch.

v3 changes:
* Default users see only the **form builder**. The Code view is gated
  to admins via :func:`task_admin.is_admin` (env: ``MARCEDIT_WEB_ADMINS``).
* Running tasks against the loaded batch routes through the subprocess
  sandbox in :mod:`marcedit_web.lib.sandbox`. The Streamlit process
  never executes user code directly.
* Task files keep round-tripping through the existing
  ``editor.parse_user_task_file`` / ``task_builder.parse_ops_from_source``
  / ``task_builder.render_ops_to_python`` plumbing. Form-built tasks
  carry ``# OP:`` markers so re-opening them returns to form view.

TASK-050: tasks are stored in the SQLite ``tasks`` table with a
private/shared visibility flag. Files on disk are still the
loader's contract; ``task_db.materialize_to_dir`` writes each
visible task to a per-session ``/tmp/marcedit-web-tasks-<sid>/``
on every render. Save / delete / visibility writes go to SQL.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    ai_task_draft,
    batch_replace,
    editor,
    gemini_task_draft,
    marcedit_import,
    note_task_draft,
    quotas,
    provenance,
    quick_batch,
    run_history,
    sandbox,
    session,
    snapshot_actions,
    task_admin,
    task_builder,
    task_db,
    task_diff,
    tasks,
)
from marcedit_web.lib.audit import audit_event
from marcedit_web.lib.batch_replace import BatchReplaceRequest
from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.run_history import TaskRunRecord
from marcedit_web.lib.errors import Issue, transform_issue
from marcedit_web.lib.task_builder import OPERATIONS_PALETTE, Operation
from marcedit_web.render.batch_status import loaded_batch_status

logger = logging.getLogger("marcedit_web.render.tasks")


# ---------------------------------------------------------------------------
# Session-state keys (Stage 22)
#
# Single source of truth for every ``tasks_*`` key the editor flow writes
# into ``st.session_state``. A typo at a callsite now becomes an
# ImportError / AttributeError instead of a silent state-leak bug where
# the editor reads from one key and writes to another. Widget ``key=``
# arguments use the same constants so a future rename is one find.
# ---------------------------------------------------------------------------

K_EDITOR_OPEN = "tasks_editor_open"
K_EDITOR_MODE = "tasks_editor_mode"
K_EDITOR_NAME = "tasks_editor_name"
K_EDITOR_DESCRIPTION = "tasks_editor_description"
K_EDITOR_BODY = "tasks_editor_body"
K_EDITOR_OPS = "tasks_editor_ops"
K_EDITOR_ORIGINAL_NAME = "tasks_editor_original_name"
K_EDITOR_VISIBILITY = "tasks_editor_visibility"
K_EDITOR_NAME_INPUT = "tasks_editor_name_input"
K_EDITOR_DESCRIPTION_INPUT = "tasks_editor_description_input"
K_EDITOR_FROM_AI_DRAFT = "tasks_editor_from_ai_draft"
K_EDITOR_AI_DRAFT_REVIEW = "tasks_editor_ai_draft_review"
K_RUN_RESULTS = "tasks_run_results"
K_SAVE_ERROR = "tasks_save_error"
K_SAVE_SUCCESS = "tasks_save_success"
K_MATERIALIZED_DIR = "tasks_materialized_dir"
K_AI_DRAFT_NOTES = "tasks_ai_draft_notes"
K_AI_DRAFT_REVIEW = "tasks_ai_draft_review"
K_AI_DRAFT_ERROR = "tasks_ai_draft_error"
K_AI_DRAFT_BLOCKING_ACK = "tasks_ai_draft_blocking_ack"
K_QB_DOWNLOAD_READY = "quick_batch_download_ready"

# TASK-143: workspace mode switcher.
MODE_RUN = "Run"
MODE_QUICK = "Quick operations"
MODE_BUILD = "Build & import"
_MODES = (MODE_RUN, MODE_QUICK, MODE_BUILD)
K_MODE_WIDGET = "tasks_workspace_mode"
# Editor-open callbacks run after the radio has been instantiated, and
# Streamlit forbids assigning a widget's own key mid-run. They write the
# force key instead; the next run pops it into the widget key before the
# radio renders.
K_FORCE_MODE = "tasks_workspace_mode_force"


def _materialized_dir(user: str) -> Path:
    """Per-session tmp dir holding the user's visible tasks as .py files.

    Created lazily once per Streamlit session. The dir is re-populated
    on every page render by ``task_db.materialize_to_dir`` — cheap,
    because that helper only rewrites files whose content changed.

    Lifecycle: tied to ``st.session_state``; reclaimed when the
    session ends (the OS cleans ``/tmp`` on container restart, and a
    long-lived container can be swept via the standard ``find /tmp
    -name 'marcedit-web-*' -mtime +2`` cron documented in deployment.md).
    """
    if K_MATERIALIZED_DIR not in st.session_state:
        sid = uuid.uuid4().hex[:8]
        st.session_state[K_MATERIALIZED_DIR] = (
            Path(tempfile.gettempdir()) / f"marcedit-web-tasks-{sid}"
        )
    target = st.session_state[K_MATERIALIZED_DIR]
    target.mkdir(parents=True, exist_ok=True)
    return target


def _refresh_tasks_for(user: str) -> Path:
    """Materialize visible tasks for ``user`` and return the dir.

    Call this before reading the task registry. Idempotent.
    """
    target = _materialized_dir(user)
    task_db.materialize_to_dir(user, target)
    return target


def render() -> None:
    """Render the Tasks tab into the current Streamlit container."""
    current_user_id = session.current_user_id()
    is_admin = task_admin.is_admin(current_user_id)
    tasks_dir = _refresh_tasks_for(current_user_id)

    # Editor draft state — namespaced.
    st.session_state.setdefault(K_EDITOR_OPEN, False)
    st.session_state.setdefault(K_EDITOR_MODE, "form")  # "form" | "code"
    st.session_state.setdefault(K_EDITOR_NAME, "")
    st.session_state.setdefault(K_EDITOR_DESCRIPTION, "")
    st.session_state.setdefault(K_EDITOR_BODY, "")
    st.session_state.setdefault(K_EDITOR_OPS, [])  # list[dict] — Operation.to_dict()
    st.session_state.setdefault(K_EDITOR_ORIGINAL_NAME, None)
    st.session_state.setdefault(K_EDITOR_VISIBILITY, "private")
    st.session_state.setdefault(K_EDITOR_FROM_AI_DRAFT, False)
    st.session_state.setdefault(K_EDITOR_AI_DRAFT_REVIEW, None)
    st.session_state.setdefault(K_RUN_RESULTS, None)

    # Load the materialized dir so the importer sees the user's tasks.
    tasks.load_user_tasks(tasks_dir, force_reload=False)
    registered = tasks.all_tasks()

    loaded_batch_status()

    forced = st.session_state.pop(K_FORCE_MODE, None)
    if forced in _MODES:
        st.session_state[K_MODE_WIDGET] = forced
    mode = st.radio(
        "Tasks workspace mode",
        _MODES,
        horizontal=True,
        key=K_MODE_WIDGET,
        label_visibility="collapsed",
    )
    st.divider()

    if mode == MODE_QUICK:
        _render_quick_ops_mode()
    elif mode == MODE_BUILD:
        _render_build_mode(tasks_dir, is_admin, current_user_id, registered)
    else:
        _render_run_mode(registered, tasks_dir)


def _render_run_mode(registered, tasks_dir: Path) -> None:
    """Run saved tasks against the loaded batch and review the results."""
    st.subheader("Run on loaded batch")
    if not session.has_upload():
        # Don't use session.require_upload() here — the standard banner
        # says "this feature reads records already in this session,"
        # but Tasks can be *authored* without a loaded batch (we want
        # the user to keep building/importing tasks even pre-upload).
        # A bespoke message is the right call.
        st.info(
            "Upload a `.mrc` file on the **Home** page to run tasks "
            "against it. Tasks can be built and imported without a "
            "loaded batch."
        )
    elif not registered:
        st.info(
            "Create or import at least one task in **Build & import** "
            "to enable running."
        )
    else:
        _render_run_panel(registered, tasks_dir)
    _render_run_results()


def _render_quick_ops_mode() -> None:
    """One-shot find/replace and canned batch operations."""
    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on the **Home** page to use quick "
            "operations."
        )
        return
    _render_quick_find_replace()
    _render_quick_batch_operations()


def _render_build_mode(
    tasks_dir: Path, is_admin: bool, current_user_id: str, registered
) -> None:
    """Manage, author, and import task definitions."""
    # --- Counts banner + admin badge --------------------------------------

    counts = task_db.count_visible(current_user_id)
    own_tasks = task_db.list_own_tasks(current_user_id)
    cnt_a, cnt_b, cnt_c, cnt_d = st.columns([2, 2, 2, 2])
    cnt_a.metric("Yours", counts["own"])
    cnt_b.metric("Shared with you", counts["shared_from_others"])
    cnt_c.metric("Registered", len(registered))
    if cnt_d.button("Clear my tasks", key="tasks_clear_mine"):
        for t in own_tasks:
            try:
                task_db.delete_task(current_user_id, t["name"])
                tasks.TASK_REGISTRY.pop(t["name"], None)
            except Exception as exc:  # noqa: BLE001
                logger.exception("delete_task failed for %s", t["name"])
                st.warning(f"Could not delete {t['name']}: {exc}")
        st.session_state[K_EDITOR_OPEN] = False
        st.rerun()

    if not is_admin:
        st.caption(
            "ℹ️ You're using the **form builder** path. Raw-Python task "
            "authoring is restricted to administrators (see "
            "`MARCEDIT_WEB_ADMINS`)."
        )

    # --- Existing tasks list ----------------------------------------------

    st.subheader("Existing tasks")
    visible = task_db.list_visible_tasks(current_user_id)
    if not visible:
        st.info(
            "No tasks defined yet. Use **+ New task** below or **Import "
            "from MarcEdit** to convert an existing `.tasksfile`."
        )
    else:
        for row in visible:
            owned = row["owner_email"] == current_user_id
            cols = st.columns([3, 4, 1, 1, 1])
            label = f"**`{row['name']}`**"
            if row["visibility"] == "shared":
                label += " &nbsp; :material/share: shared"
            if not owned:
                label += f" &nbsp; _by {row['owner_email']}_"
            cols[0].markdown(label, unsafe_allow_html=False)
            cols[1].caption(row["description"] or "_(no description)_")
            if owned:
                if cols[2].button("Edit", key=f"edit_{row['name']}"):
                    _open_editor_for_existing_row(row, is_admin)
                    st.rerun()
                # Toggle visibility in-place.
                new_vis = "shared" if row["visibility"] == "private" else "private"
                vis_label = "Share" if new_vis == "shared" else "Unshare"
                if cols[3].button(vis_label, key=f"vis_{row['name']}"):
                    task_db.set_visibility(current_user_id, row["name"], new_vis)
                    audit_event(
                        "task-visibility-changed",
                        user=current_user_id,
                        task_name=row["name"],
                        from_visibility=row["visibility"],
                        to_visibility=new_vis,
                    )
                    st.rerun()
                if cols[4].button("Delete", key=f"del_{row['name']}"):
                    task_db.delete_task(current_user_id, row["name"])
                    tasks.TASK_REGISTRY.pop(row["name"], None)
                    audit_event(
                        "task-deleted",
                        user=current_user_id,
                        task_name=row["name"],
                    )
                    st.rerun()
            else:
                # Shared task by someone else — runnable, not editable.
                cols[2].caption("_read-only_")
                cols[3].empty()
                cols[4].empty()

    # --- New / import controls --------------------------------------------

    col_new, col_import = st.columns(2)
    with col_new:
        if st.button("+ New task", key="tasks_new"):
            _open_editor_for_new()
            st.rerun()
    with col_import:
        upl = st.file_uploader(
            "Import a MarcEdit .tasksfile (`.txt`) or `.task` archive",
            type=["txt", "task"],
            accept_multiple_files=False,
            key="tasks_import_uploader",
        )
        if upl is not None and st.button("Import", key="tasks_import_btn"):
            _do_marcedit_import(upl, tasks_dir)
            st.rerun()

    _render_ai_draft_panel()
    if st.session_state.get(K_AI_DRAFT_REVIEW) is not None:
        _render_ai_draft_review()

    # --- Editor (form or code) --------------------------------------------

    if st.session_state[K_EDITOR_OPEN]:
        _render_editor(tasks_dir, is_admin)


# ---------------------------------------------------------------------------
# Editor state helpers
# ---------------------------------------------------------------------------


def _open_editor_for_new() -> None:
    """Open the editor for a brand-new task in form mode."""
    st.session_state[K_FORCE_MODE] = MODE_BUILD
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_MODE] = "form"
    st.session_state[K_EDITOR_NAME] = ""
    st.session_state[K_EDITOR_DESCRIPTION] = ""
    _sync_editor_widget_inputs("", "")
    st.session_state[K_EDITOR_BODY] = (
        "# `record` is a pymarc.Record. Mutate it in place; do not return.\n"
        "# Example: delete every 029 field.\n"
        "#\n"
        "# from marcedit_web.lib.transforms import delete_tags\n"
        "# delete_tags(record, \"029\")\n"
        "pass\n"
    )
    st.session_state[K_EDITOR_OPS] = []
    st.session_state[K_EDITOR_ORIGINAL_NAME] = None
    st.session_state[K_EDITOR_VISIBILITY] = "private"
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None


def _open_editor_for_existing_row(row: dict, is_admin: bool) -> None:
    """Open the editor pre-populated from a SQL task row.

    ``row`` is a dict from ``task_db.list_visible_tasks`` /
    ``task_db.get_task`` — has ``name``, ``description``, ``body``,
    ``visibility``. Form vs code mode is chosen by re-parsing the
    body via ``task_builder.parse_ops_from_source`` (same logic as
    the legacy file-based path).
    """
    st.session_state[K_FORCE_MODE] = MODE_BUILD
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_NAME] = row["name"]
    st.session_state[K_EDITOR_DESCRIPTION] = row["description"]
    _sync_editor_widget_inputs(row["name"], row["description"])
    st.session_state[K_EDITOR_BODY] = row["body"]
    st.session_state[K_EDITOR_ORIGINAL_NAME] = row["name"]
    st.session_state[K_EDITOR_VISIBILITY] = row["visibility"]
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None

    parse_result = task_builder.parse_ops_from_source(row["body"])
    if parse_result["form_editable"]:
        st.session_state[K_EDITOR_MODE] = "form"
        st.session_state[K_EDITOR_OPS] = [
            op.to_dict() for op in parse_result["ops"]
        ]
    else:
        # Hand-written: code mode if admin, else read-only-style notice.
        st.session_state[K_EDITOR_MODE] = "code" if is_admin else "form"
        st.session_state[K_EDITOR_OPS] = []


def _archive_scratch_path(tasks_dir: Path, upl_name: str) -> Path:
    """Return a traversal-safe scratch path inside ``tasks_dir`` for an upload.

    The client-supplied filename is reduced to a bare basename (NUL stripped)
    and prefixed with a unique token, so it can never redirect the write
    outside ``tasks_dir`` (path traversal) and concurrent imports of like-named
    files don't collide. The ``.__import__<uuid>_`` prefix is load-bearing for
    safety, not just collisions: it keeps even a basename of ``..`` a literal
    child filename rather than resolving to the parent directory. (TASK-071)
    """
    safe = Path(upl_name).name.replace("\x00", "") or "import.task"
    return tasks_dir / f".__import__{uuid.uuid4().hex}_{safe}"


def _convert_uploaded_archive(
    tasks_dir: Path, upl_name: str, raw: bytes
) -> "marcedit_import.ArchiveConversionResult":
    """Write the uploaded ``.task`` archive bytes to a traversal-safe scratch
    file inside ``tasks_dir``, convert it, and always remove the scratch file.
    """
    scratch = _archive_scratch_path(tasks_dir, upl_name)
    try:
        scratch.write_bytes(raw)
        return marcedit_import.convert_task_archive(scratch)
    finally:
        scratch.unlink(missing_ok=True)


def _do_marcedit_import(upl, tasks_dir: Path) -> None:
    """Import a MarcEdit `.tasksfile` or `.task` archive into SQL.

    Imported tasks land as private rows owned by the current user.
    Operators can re-share via the visibility toggle. ``tasks_dir`` is
    used as a scratch path for archive extraction; the persistent
    storage is the SQLite ``tasks`` table.
    """
    user = session.current_user_id()
    raw = upl.getvalue()
    is_archive = upl.name.lower().endswith(".task")
    # Tasksfiles are text → 1 MB cap. Archives can be larger because
    # they bundle multiple inner txt entries, but each inner entry is
    # gated again inside convert_task_archive.
    quota_kind = "upload" if is_archive else "tasksfile"
    try:
        quotas.check_upload(len(raw), kind=quota_kind)
    except quotas.QuotaExceeded as exc:
        audit_event(
            "tasksfile-rejected" if not is_archive else "archive-rejected",
            user=user,
            filename=upl.name,
            size=len(raw),
            reason=exc.kind,
            limit=exc.limit,
        )
        st.error(f"Import rejected: {exc}")
        return

    try:
        if is_archive:
            archive = _convert_uploaded_archive(tasks_dir, upl.name, raw)
            if archive.archive_errors:
                for err in archive.archive_errors:
                    st.error(err)
                audit_event(
                    "archive-rejected",
                    user=user,
                    filename=upl.name,
                    size=len(raw),
                    reason="archive-errors",
                    detail=archive.archive_errors[:3],
                )
                return
            imported = 0
            for er in archive.entries:
                if er.success and er.conversion is not None:
                    conv = er.conversion
                    task_db.save_task(
                        owner=user,
                        name=conv.name,
                        description=conv.description or "",
                        body=conv.body,
                        extra_imports=conv.imports,
                        visibility="private",
                    )
                    imported += 1
                elif er.error:
                    st.warning(f"{er.entry_name}: {er.error}")
            st.success(f"Imported {imported} task(s) from `{upl.name}`.")
            audit_event(
                "archive-imported",
                user=user,
                filename=upl.name,
                size=len(raw),
                imported=imported,
                entries=len(archive.entries),
            )
        else:
            name = marcedit_import._derive_name_from_filename(upl.name)
            conv = marcedit_import.convert_tasksfile_text(
                raw.decode("utf-8"),
                name=name,
                description_fallback=f"Imported from {upl.name}",
            )
            task_db.save_task(
                owner=user,
                name=conv.name,
                description=conv.description or "",
                body=conv.body,
                extra_imports=conv.imports,
                visibility="private",
            )
            st.success(f"Imported `{conv.name}` from `{upl.name}`.")
            audit_event(
                "tasksfile-imported",
                user=user,
                filename=upl.name,
                size=len(raw),
                task_name=conv.name,
                unsupported_lines=len(conv.unsupported),
            )
            if conv.unsupported:
                st.warning(
                    f"{len(conv.unsupported)} source line(s) were not "
                    "translated; they appear as `# TODO` comments in the "
                    "imported task body."
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("MarcEdit import failed")
        st.error(f"Import failed: {exc}")
        audit_event(
            "tasksfile-rejected" if not is_archive else "archive-rejected",
            user=user,
            filename=upl.name,
            size=len(raw),
            reason="exception",
            detail=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Task draft panel
# ---------------------------------------------------------------------------


def _render_ai_draft_panel() -> None:
    with st.expander("Draft task from notes"):
        gemini_enabled = gemini_task_draft.is_enabled()
        if not gemini_enabled:
            st.info(
                "Local note parsing is available. Set GEMINI_API_KEY to enable "
                "Gemini fallback for unresolved lines."
            )
        with st.expander("Supported note syntax", expanded=False):
            st.code(note_task_draft.help_text(), language="text")

        notes = st.text_area(
            "Cataloger notes",
            value=st.session_state.get(K_AI_DRAFT_NOTES, ""),
            key=K_AI_DRAFT_NOTES,
            height=160,
        )
        if st.button(
            "Draft task",
            key="tasks_ai_draft_btn",
            disabled=(not notes.strip()),
        ):
            try:
                review = note_task_draft.draft_task_from_notes(notes)
            except ai_task_draft.DraftValidationError as exc:
                _store_ai_draft_error(str(exc))
            else:
                _store_ai_draft_review(review)
                audit_event(
                    "ai-task-draft-created",
                    user=session.current_user_id(),
                    source="deterministic",
                    task_name=review.task_name,
                    accepted_operations=len(review.operations),
                    blocking_issues=ai_task_draft.blocking_issue_count(review),
                )
                st.rerun()

        if st.session_state.get(K_AI_DRAFT_ERROR):
            st.error(st.session_state[K_AI_DRAFT_ERROR])

        review = st.session_state.get(K_AI_DRAFT_REVIEW)
        if review is not None and _ai_fallback_available(review):
            if st.button(
                "Use Gemini for unresolved lines",
                key="tasks_gemini_fallback_btn",
            ):
                try:
                    gemini_review = gemini_task_draft.draft_task_from_notes(
                        note_task_draft.unresolved_text(review)
                    )
                except (
                    gemini_task_draft.GeminiTaskDraftError,
                    ai_task_draft.DraftValidationError,
                ) as exc:
                    _store_ai_draft_error(str(exc))
                else:
                    merged_review = note_task_draft.merge_fallback_review(
                        review, gemini_review
                    )
                    _store_ai_draft_review(merged_review)
                    audit_event(
                        "ai-task-draft-created",
                        user=session.current_user_id(),
                        source="gemini-fallback",
                        task_name=merged_review.task_name,
                        accepted_operations=len(merged_review.operations),
                        blocking_issues=ai_task_draft.blocking_issue_count(
                            merged_review
                        ),
                    )
                    st.rerun()


def _render_ai_draft_review() -> None:
    review = st.session_state[K_AI_DRAFT_REVIEW]
    blocking_issues = ai_task_draft.blocking_issue_count(review)
    st.subheader("Task draft review")
    st.markdown(f"**Proposed task:** `{review.task_name}`")
    description = _ai_draft_review_description(review)
    st.caption(description or "_No description proposed._")

    if review.operations:
        st.markdown("**Generated operations**")
        for index, op in enumerate(review.operations, start=1):
            st.markdown(f"{index}. {_ai_draft_operation_summary(op)}")
    else:
        st.info("No supported operations were generated.")

    _render_ai_draft_list("Manual notes", review.manual_notes)
    _render_ai_draft_list("Unsupported lines", review.unsupported_lines)
    _render_ai_draft_list("Questions", review.questions)

    if review.rejected_operations:
        st.markdown("**Rejected operations**")
        for rejected in review.rejected_operations:
            st.warning(_ai_draft_rejected_operation_summary(rejected))

    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = blocking_issues == 0
    if blocking_issues:
        st.warning(
            f"{blocking_issues} task draft issue(s) need review before this "
            "draft can be saved as a new task."
        )

    use_col, clear_col = st.columns([1, 1])
    if use_col.button(
        "Use this draft in form editor",
        key="tasks_ai_draft_use",
        type="primary",
        disabled=_ai_draft_handoff_disabled(review),
    ):
        _open_editor_for_ai_draft(review)
        st.rerun()
    if clear_col.button("Clear draft", key="tasks_ai_draft_clear"):
        _clear_ai_draft_review()
        st.rerun()


def _render_ai_draft_list(label: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values:
        st.markdown(f"- {value}")


def _ai_draft_review_description(review: ai_task_draft.DraftReview) -> str:
    return review.description


def _ai_draft_operation_summary(op: ai_task_draft.DraftOperation) -> str:
    pieces = [f"`{op.kind}`"]
    if op.confidence:
        pieces.append(f"confidence: {op.confidence}")
    if op.explanation:
        pieces.append(op.explanation)

    detail = _ai_draft_operation_detail(op)
    if detail:
        pieces.append(detail)
    return " — ".join(pieces)


def _ai_draft_rejected_operation_summary(
    op: ai_task_draft.RejectedOperation,
) -> str:
    pieces = [f"`{op.kind or '(missing kind)'}`"]
    if op.reason:
        pieces.append(op.reason)
    if op.source_text:
        pieces.append(f"source: {op.source_text}")
    return " — ".join(pieces)


def _ai_draft_operation_detail(op: ai_task_draft.DraftOperation) -> str:
    params = op.params or {}
    regex = op.regex or {}
    parts = []
    for key in ("pattern", "meaning", "before", "after"):
        value = regex.get(key)
        if value is None:
            value = params.get(key)
        if value not in (None, ""):
            parts.append(f"{key}: {value}")
    return "; ".join(parts)


def _open_editor_for_ai_draft(review: ai_task_draft.DraftReview) -> None:
    st.session_state[K_FORCE_MODE] = MODE_BUILD
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_MODE] = "form"
    st.session_state[K_EDITOR_NAME] = review.task_name
    description = _ai_draft_review_description(review)
    st.session_state[K_EDITOR_DESCRIPTION] = description
    _sync_editor_widget_inputs(review.task_name, description)
    st.session_state[K_EDITOR_BODY] = ""
    st.session_state[K_EDITOR_OPS] = ai_task_draft.operations_for_editor(review)
    st.session_state[K_EDITOR_ORIGINAL_NAME] = None
    st.session_state[K_EDITOR_VISIBILITY] = "private"
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = True
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = review


def _ai_draft_save_blocked_for_new_task() -> bool:
    if not st.session_state.get(K_EDITOR_FROM_AI_DRAFT, False):
        return False
    review = st.session_state.get(K_EDITOR_AI_DRAFT_REVIEW)
    if review is None:
        return False
    if st.session_state.get(K_EDITOR_ORIGINAL_NAME) is not None:
        return False
    return ai_task_draft.blocking_issue_count(review) > 0


def _ai_draft_handoff_disabled(review: ai_task_draft.DraftReview) -> bool:
    return not review.operations


def _ai_fallback_available(review: ai_task_draft.DraftReview) -> bool:
    return (
        gemini_task_draft.is_enabled()
        and bool(note_task_draft.unresolved_text(review).strip())
    )


def _sync_editor_widget_inputs(name: str, description: str) -> None:
    st.session_state[K_EDITOR_NAME_INPUT] = name
    st.session_state[K_EDITOR_DESCRIPTION_INPUT] = description


def _clear_ai_draft_review() -> None:
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False
    st.session_state[K_AI_DRAFT_ERROR] = None
    if st.session_state.get(K_EDITOR_FROM_AI_DRAFT, False):
        st.session_state[K_EDITOR_OPEN] = False
        st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
        st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None


def _store_ai_draft_error(message: str) -> None:
    st.session_state[K_AI_DRAFT_ERROR] = message
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False


def _store_ai_draft_review(review: ai_task_draft.DraftReview) -> None:
    st.session_state[K_AI_DRAFT_REVIEW] = review
    st.session_state[K_AI_DRAFT_ERROR] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False


# ---------------------------------------------------------------------------
# Editor renderer (form + code)
# ---------------------------------------------------------------------------


def _render_editor(tasks_dir: Path, is_admin: bool) -> None:
    st.divider()
    is_edit = st.session_state[K_EDITOR_ORIGINAL_NAME] is not None
    st.subheader(
        f"Edit `{st.session_state[K_EDITOR_ORIGINAL_NAME]}`"
        if is_edit
        else "New task"
    )

    # Mode toggle: admins see it, standard users are pinned to form.
    if is_admin:
        mode = st.radio(
            "Editor mode",
            options=["form", "code"],
            index=0 if st.session_state[K_EDITOR_MODE] == "form" else 1,
            horizontal=True,
            key="tasks_editor_mode_radio",
            help=(
                "Code view writes raw Python; form view builds tasks from "
                "a typed operation palette. Both run through the subprocess "
                "sandbox at execution time."
            ),
        )
        st.session_state[K_EDITOR_MODE] = mode
    else:
        # Standard users are pinned to form view regardless of state.
        st.session_state[K_EDITOR_MODE] = "form"

    st.session_state[K_EDITOR_NAME] = st.text_input(
        "Task name (lowercase, digits, hyphens)",
        value=st.session_state[K_EDITOR_NAME],
        help="Used in the @task(...) decorator. Must be unique.",
        key=K_EDITOR_NAME_INPUT,
    )
    st.session_state[K_EDITOR_DESCRIPTION] = st.text_input(
        "Description (one sentence)",
        value=st.session_state[K_EDITOR_DESCRIPTION],
        key=K_EDITOR_DESCRIPTION_INPUT,
    )

    vis_default = st.session_state.get(K_EDITOR_VISIBILITY, "private")
    st.session_state[K_EDITOR_VISIBILITY] = st.radio(
        "Visibility",
        options=["private", "shared"],
        index=0 if vis_default == "private" else 1,
        horizontal=True,
        key="tasks_editor_visibility_radio",
        help=(
            "**Private** — only you see this task. "
            "**Shared** — every signed-in user can see and run it; "
            "only you can edit or delete."
        ),
    )

    if st.session_state[K_EDITOR_MODE] == "form":
        _render_form_editor()
    else:
        _render_code_editor()

    save_disabled = _ai_draft_save_blocked_for_new_task()
    if save_disabled:
        st.warning(
            "Resolve the blocking task draft review items before saving this "
            "new task."
        )

    save_col, cancel_col = st.columns([1, 1])
    save_col.button(
        "Save task",
        type="primary",
        key="tasks_save",
        on_click=_save_callback,
        args=(tasks_dir,),
        disabled=save_disabled,
    )
    cancel_col.button(
        "Cancel",
        key="tasks_cancel",
        on_click=_cancel_callback,
    )

    # Display any pending success/error from the last save attempt.
    if st.session_state.get(K_SAVE_ERROR):
        st.error(st.session_state.pop(K_SAVE_ERROR))
    if st.session_state.get(K_SAVE_SUCCESS):
        st.success(st.session_state.pop(K_SAVE_SUCCESS))


def _render_code_editor() -> None:
    st.caption(
        "Code view. Write the function **body only**. `record` is a "
        "`pymarc.Record`; import helpers from `marcedit_web.lib.transforms` "
        "as needed."
    )
    new_body = st_ace(
        value=st.session_state[K_EDITOR_BODY],
        language="python",
        theme="github",
        keybinding="vscode",
        font_size=13,
        tab_size=4,
        wrap=True,
        show_gutter=True,
        show_print_margin=False,
        auto_update=False,
        min_lines=10,
        key="tasks_editor_ace",
    )
    if new_body is not None:
        st.session_state[K_EDITOR_BODY] = new_body


def _render_form_editor() -> None:
    """Render the operation-palette form editor.

    The op list lives in ``st.session_state[K_EDITOR_OPS]`` as a
    list of dicts (``Operation.to_dict()`` shape). Save converts it
    back to Python via ``task_builder.render_ops_to_python``.
    """
    st.caption(
        "Pick operations from the dropdown below. Each operation runs in "
        "order against every record. See the **operation reference** "
        "expander for what each does."
    )

    is_admin = task_admin.is_admin(
        session.current_user_id()
    )
    ops = st.session_state[K_EDITOR_OPS]
    to_remove: list[int] = []

    # Non-admin users mustn't be able to author raw Python through the
    # custom-op textarea. We filter `custom` out of the *add* dropdown
    # below, but an imported/pre-existing task may already carry one;
    # warn the cataloger so they understand the editor is read-only on
    # that op.
    if not is_admin and any(op.get("kind") == "custom" for op in ops):
        st.warning(
            "This task contains a **`custom`** op with raw Python. You're "
            "not an admin, so its code is shown read-only. Save will "
            "preserve the existing code unchanged; to edit it ask an "
            "admin or use a typed op above."
        )

    for i, op in enumerate(ops):
        with st.container():
            st.markdown(f"**{i + 1}. `{op['kind']}`**")
            palette_entry = _palette_entry(op["kind"])
            if palette_entry is None:
                st.warning(
                    f"Unknown operation kind `{op['kind']}` — was it "
                    "renamed? Remove and re-add to fix."
                )
            else:
                st.caption(palette_entry.get("summary", ""))
                # Render each param.
                params = op.setdefault("params", {})
                for param in palette_entry["params"]:
                    _render_param_input(
                        param, params, key_prefix=f"op_{i}",
                        is_admin=is_admin,
                    )

            row = st.columns([1, 1, 6])
            if row[0].button("↑", key=f"op_up_{i}", disabled=i == 0):
                ops[i - 1], ops[i] = ops[i], ops[i - 1]
                st.rerun()
            if row[1].button("↓", key=f"op_down_{i}", disabled=i == len(ops) - 1):
                ops[i + 1], ops[i] = ops[i], ops[i + 1]
                st.rerun()
            if row[2].button("Remove", key=f"op_rm_{i}"):
                to_remove.append(i)
            st.divider()

    if to_remove:
        for i in reversed(to_remove):
            ops.pop(i)
        st.rerun()

    add_options = [op["kind"] for op in OPERATIONS_PALETTE]
    if not is_admin:
        add_options = [k for k in add_options if k != "custom"]
    col_pick, col_btn = st.columns([4, 1])
    new_kind = col_pick.selectbox(
        "Add operation",
        options=add_options,
        format_func=lambda k: _palette_entry(k)["label"] if _palette_entry(k) else k,
        key="tasks_form_add_kind",
    )
    if col_btn.button("+ Add", key="tasks_form_add_btn"):
        ops.append({"kind": new_kind, "params": _default_params_for(new_kind)})
        st.rerun()

    with st.expander("Operation reference"):
        for entry in OPERATIONS_PALETTE:
            st.markdown(f"**{entry['label']}** (`{entry['kind']}`) — {entry['summary']}")


# ---------------------------------------------------------------------------
# Form input rendering
# ---------------------------------------------------------------------------


def _palette_entry(kind: str) -> dict | None:
    for entry in OPERATIONS_PALETTE:
        if entry["kind"] == kind:
            return entry
    return None


def _default_params_for(kind: str) -> dict:
    entry = _palette_entry(kind)
    if entry is None:
        return {}
    out = {}
    for param in entry["params"]:
        if "default" in param:
            out[param["name"]] = param["default"]
        elif param["type"] == "bool":
            out[param["name"]] = False
        elif param["type"] == "subfields":
            out[param["name"]] = []
        else:
            out[param["name"]] = ""
    return out


def _render_param_input(
    param: dict, params: dict, *, key_prefix: str, is_admin: bool = False
) -> None:
    """Render one form widget for one operation parameter.

    ``is_admin`` gates the ``code`` ptype: for non-admins, the textarea
    is replaced by a read-only ``st.code`` block. This protects the
    "form-builder only for standard users" trust model against imported
    tasks that already carry a ``custom`` op — the existing code is
    visible, but the cataloger can't modify it from the form editor.
    """
    name = param["name"]
    label = param["label"]
    ptype = param["type"]
    help_text = param.get("help") or param.get("placeholder") or None
    key = f"{key_prefix}_{name}"

    current = params.get(name, param.get("default", ""))

    if ptype == "text":
        params[name] = st.text_input(
            label, value=current, placeholder=param.get("placeholder", ""),
            help=help_text, key=key,
        )
    elif ptype == "bool":
        params[name] = st.checkbox(
            label, value=bool(current), help=help_text, key=key,
        )
    elif ptype == "indicator":
        params[name] = st.text_input(
            label, value=str(current)[:1] or " ", max_chars=1,
            help=help_text or "Single character; space for blank.",
            key=key,
        )
    elif ptype == "subfield_code":
        params[name] = st.text_input(
            label, value=str(current)[:1], max_chars=1,
            help=help_text or "Single character: a-z or 0-9.",
            key=key,
        )
    elif ptype == "subfields":
        # Subfields are a list of (code, value) pairs. Render as a JSON
        # textarea for compactness; a richer per-row editor can come in
        # v3.5.
        raw = st.text_area(
            label,
            value=json.dumps(current or [], ensure_ascii=False, indent=2),
            help=(
                'JSON list of [code, value] pairs. Example: '
                '`[["a", "Title"], ["c", "by Author"]]`. '
                + (help_text or "")
            ),
            key=key,
        )
        try:
            params[name] = json.loads(raw)
        except json.JSONDecodeError:
            st.warning(
                f"`{label}`: not valid JSON; previous value preserved."
            )
    elif ptype == "select":
        options = [opt["value"] for opt in param.get("options", [])]
        labels = {opt["value"]: opt["label"] for opt in param.get("options", [])}
        if current not in options and options:
            current = options[0]
        params[name] = st.selectbox(
            label, options=options,
            index=options.index(current) if current in options else 0,
            format_func=lambda v: labels.get(v, v),
            help=help_text,
            key=key,
        )
    elif ptype == "code":
        # Reached for the `custom` op. Add-op dropdown filters this out
        # for non-admins, but imported tasks (e.g. via MarcEdit
        # tasksfile import that fell through to `custom`) can still
        # carry one. For non-admins we render read-only so the existing
        # code stays visible but can't be mutated. ``params[name]``
        # is intentionally left unchanged in that branch.
        if is_admin:
            params[name] = st.text_area(
                label, value=str(current or ""),
                help=help_text or "Raw Python; runs in the sandbox.",
                key=key,
                height=200,
            )
        else:
            st.caption(
                f"**{label}** — read-only (admin Code-view required to edit)"
            )
            st.code(str(current or "# (empty)"), language="python")
    else:
        st.warning(f"Unsupported param type `{ptype}` for {name}.")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _save_callback(tasks_dir: Path) -> None:
    """on_click callback for Save. Runs BEFORE Streamlit's iteration phase
    so mutations of TASK_REGISTRY / session_state don't trip the
    dict-changed-size error in `_call_callbacks`.

    Writes the task to SQL via task_db, re-materializes the user's
    visible-task dir, and reloads the importer.
    """
    name = (st.session_state.get(K_EDITOR_NAME_INPUT)
            or st.session_state.get(K_EDITOR_NAME) or "").strip()
    description = (
        st.session_state.get(K_EDITOR_DESCRIPTION_INPUT)
        or st.session_state.get(K_EDITOR_DESCRIPTION)
        or ""
    ).strip()
    original = st.session_state.get(K_EDITOR_ORIGINAL_NAME)
    mode = st.session_state.get(K_EDITOR_MODE, "form")
    visibility = st.session_state.get(K_EDITOR_VISIBILITY, "private")
    user = session.current_user_id()

    if _ai_draft_save_blocked_for_new_task():
        st.session_state[K_SAVE_ERROR] = (
            "Resolve the blocking task draft review items before saving this "
            "new task."
        )
        return

    if mode == "form":
        ops = [
            Operation.from_dict(op)
            for op in st.session_state.get(K_EDITOR_OPS, [])
        ]
        rendered = task_builder.render_ops_to_python(ops)
        body = rendered["body"]
        extra_imports = rendered["imports"]
    else:
        body = st.session_state.get(K_EDITOR_BODY, "")
        extra_imports = None

    # Pre-flight: compile the to-be-saved file before we hit SQL, so
    # a syntax error keeps the existing row intact.
    try:
        preview = editor.serialize_user_task(
            name, description, body, extra_imports=extra_imports,
        )
        compile(preview, f"<{name}>", "exec")
    except (ValueError, SyntaxError) as exc:
        st.session_state[K_SAVE_ERROR] = (
            str(exc) if isinstance(exc, ValueError)
            else f"task code has a syntax error: {exc.msg} (line {exc.lineno})"
        )
        return

    try:
        # Rename support: if the user changed the name, delete the
        # old row before inserting the new one. Visibility carries
        # forward unless the editor changed it.
        if original and original != name:
            task_db.delete_task(user, original)
        task_db.save_task(
            owner=user,
            name=name,
            description=description,
            body=body,
            extra_imports=extra_imports,
            visibility=visibility,
        )
    except ValueError as exc:
        st.session_state[K_SAVE_ERROR] = str(exc)
        return

    if original and original != name:
        tasks.TASK_REGISTRY.pop(original, None)
    tasks.TASK_REGISTRY.pop(name, None)
    # Re-materialize and reload so the running registry matches SQL.
    task_db.materialize_to_dir(user, tasks_dir)
    tasks.load_user_tasks(tasks_dir, force_reload=True)
    st.session_state[K_EDITOR_OPEN] = False
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False
    st.session_state[K_SAVE_SUCCESS] = f"Saved `{name}`."
    is_admin = task_admin.is_admin(user)
    audit_event(
        "task-saved",
        user=user,
        task_name=name,
        original=original,
        mode=mode,
        visibility=visibility,
        is_admin=is_admin,
        body_bytes=len(body or ""),
    )
    if mode == "code" and is_admin:
        # Admin Code-view save is the highest-trust path — surfaces a
        # second audit line so ops can filter on `admin-action` alone.
        audit_event(
            "admin-action",
            user=user,
            action="code-view-save",
            task_name=name,
        )


def _cancel_callback() -> None:
    """on_click callback for Cancel. Mirrors the on_click pattern of Save."""
    st.session_state[K_EDITOR_OPEN] = False
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None


# ---------------------------------------------------------------------------
# Run flow (sandbox)
# ---------------------------------------------------------------------------


def _render_run_panel(registered, tasks_dir: Path) -> None:
    available_names = [t.name for t in registered]
    selection = st.multiselect(
        "Tasks to run (applied in the listed order)",
        options=available_names,
        default=available_names[:1],
        help=(
            "Each task gets the same record one at a time; tasks later "
            "in the list see the output of earlier tasks. Execution "
            "happens in a sandboxed subprocess with CPU / memory / "
            "time limits."
        ),
        key="tasks_run_selection",
    )
    st.caption(
        "ℹ️ Runs apply in the sandbox, which has CPU / memory / wall-"
        "clock limits. Large batches may take up to 30 seconds — "
        "**leave this tab open until the status below reports Done**."
    )
    if st.button(
        "Run selected tasks",
        type="primary",
        disabled=not selection,
        key="tasks_run_btn",
    ):
        _execute_sandboxed_run(selection, tasks_dir)


def _execute_sandboxed_run(selection: list[str], tasks_dir: Path) -> None:
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return

    # Build TaskSpecs by reading the saved files (so we get the literal
    # body + imports the user authored, not the in-process Task fn).
    specs: list[sandbox.TaskSpec] = []
    for name in selection:
        try:
            parsed = editor.parse_user_task_file(
                editor.task_file_path(tasks_dir, name)
            )
        except (ValueError, FileNotFoundError) as exc:
            st.error(f"Could not load task `{name}`: {exc}")
            return
        specs.append(sandbox.TaskSpec(
            name=name,
            body=parsed["body"],
            imports=[],  # imports already baked into the saved file
        ))

    user = session.current_user_id()
    # Stage 20: stream the live records to a temp file instead of
    # materializing the whole batch as bytes in this process. The
    # sandbox driver opens it lazily via MARCReader and pages through.
    sandbox_workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-sandbox-"))
    sandbox_input = sandbox_workdir / "input.mrc"
    # Progress UI: a prominent in-page status block instead of the
    # top-right spinner. We can't show per-record progress (Streamlit
    # blocks on subprocess.run; no concurrent UI update path), so the
    # lines we DO emit fire at clearly-defined phase boundaries.
    with st.status(
        "Running tasks…",
        expanded=True,
    ) as status:
        st.write(f"📥 Reading **{store.count():,}** records from upload")
        input_bytes_written = store.write_mrc_to(sandbox_input)
        st.write(
            f"⚙️ Running {len(specs)} task(s) in the sandbox: "
            + ", ".join(f"`{s.name}`" for s in specs)
        )
        result = sandbox.run_tasks_subprocess(
            specs,
            input_path=sandbox_input,
            tmp_dir=sandbox_workdir,
        )
        if result.timed_out:
            status.update(
                label="⚠️ Run hit the wall-clock limit",
                state="error",
                expanded=False,
            )
        elif result.returncode != 0:
            status.update(
                label=f"⚠️ Sandbox exited with code {result.returncode}",
                state="error",
                expanded=False,
            )
        else:
            st.write("✅ Sandbox finished cleanly")
            status.update(
                label="✅ Done — review changes below before downloading",
                state="complete",
                expanded=False,
            )
    if result.timed_out:
        audit_event(
            "sandbox-timeout",
            user=user,
            tasks=list(selection),
            input_bytes=input_bytes_written,
        )
    elif result.returncode != 0:
        audit_event(
            "sandbox-nonzero-exit",
            user=user,
            tasks=list(selection),
            returncode=result.returncode,
            stderr_excerpt=(result.stderr or "")[:512],
        )

    # Re-count what we got back.
    try:
        out_records = list(pymarc.MARCReader(
            io.BytesIO(result.records_bytes),
            to_unicode=True,
            permissive=True,
        ))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse sandbox output: {exc}")
        out_records = []

    issues: list[Issue] = []
    for err in result.errors:
        issues.append(transform_issue(
            err.get("index") or 0,
            None,
            err.get("task"),
            RuntimeError(f"[{err['code']}] {err['message']}"),
        ))

    # TASK-035: compute the diff eagerly here, instead of lazily in
    # _render_diff_review. Same streaming cost either way; doing it
    # at run-completion means the audit row and TaskRunRecord carry
    # an accurate ``changed_count`` from the moment they're written.
    sandbox_output_path = sandbox_workdir / "output.mrc"
    try:
        sandbox_output_path.write_bytes(result.records_bytes or b"")
    except OSError as exc:
        logger.warning("could not write history output snapshot: %s", exc)

    diff_summary = None
    if result.returncode == 0 and not result.timed_out:
        try:
            diff_summary = task_diff.compute_task_diff(
                sandbox_input, result.records_bytes or b"",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not build task diff summary: %s", exc)

    snapshot = snapshot_actions.record_job_snapshot(
        job_id=st.session_state.get("current_job_id"),
        user_email=user,
        kind="task-run",
        label=", ".join(selection) or "Task run",
        before_bytes=sandbox_input.read_bytes(),
        after_bytes=result.records_bytes or b"",
        summary={
            "task_names": list(selection),
            "input_record_count": store.count(),
            "output_record_count": len(out_records),
            "changed_count": (
                diff_summary.changed_count if diff_summary is not None else 0
            ),
            "error_count": len(issues),
            "timed_out": bool(result.timed_out),
            "sandbox_returncode": int(result.returncode or 0),
        },
    )
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=user,
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )

    st.session_state[K_RUN_RESULTS] = {
        "issues": issues,
        "out_filename": _export_filename(session.current_filename(), "tasks"),
        "out_path": str(sandbox_output_path),
        "input_count": store.count(),
        "output_count": len(out_records),
        "ran_tasks": list(selection),
        "timed_out": result.timed_out,
        "sandbox_returncode": result.returncode,
        # Path to the streaming-input file so the diff renderer can
        # walk it again. The sandbox workdir survives until container
        # restart; that's good enough for the post-run review window.
        "sandbox_input_path": str(sandbox_input),
        # Pre-computed diff summary so _render_diff_review reuses it
        # instead of rebuilding.
        "_diff_summary": diff_summary,
        "snapshot_id": snapshot["id"] if snapshot is not None else None,
    }

    # TASK-034 + TASK-035: append to per-session run history with
    # the real changed_count threaded in from the eager diff above.
    _record_run_in_history(
        user=user,
        store=store,
        selection=list(selection),
        result=result,
        out_records_count=len(out_records),
        errors_count=len(issues),
        changed_count=(diff_summary.changed_count
                       if diff_summary is not None else 0),
        sandbox_workdir=sandbox_workdir,
        sandbox_input_path=sandbox_input,
        sandbox_output_path=sandbox_output_path,
    )


def _record_run_in_history(
    *,
    user: str,
    store,
    selection: list[str],
    result,
    out_records_count: int,
    errors_count: int,
    changed_count: int,
    sandbox_workdir: Path,
    sandbox_input_path: Path,
    sandbox_output_path: Path,
) -> None:
    """Append a TaskRunRecord; evict oldest, clean evicted workdirs."""
    record = TaskRunRecord(
        timestamp=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        user=user,
        input_filename=session.current_filename(),
        task_names=list(selection),
        input_record_count=store.count() if store is not None else 0,
        output_record_count=out_records_count,
        changed_count=changed_count,
        error_count=errors_count,
        timed_out=bool(result.timed_out),
        sandbox_returncode=int(result.returncode or 0),
        input_path=str(sandbox_input_path),
        output_path=str(sandbox_output_path),
        workdir=str(sandbox_workdir),
    )
    history = st.session_state.get("task_run_history") or []
    new_history, evicted = run_history.append_run(history, record)
    st.session_state["task_run_history"] = new_history
    run_history.cleanup_workdirs(evicted)

    audit_event(
        "task-run-completed",
        user=user,
        tasks=record.task_names,
        input_records=record.input_record_count,
        output_records=record.output_record_count,
        changed_count=record.changed_count,
        error_count=record.error_count,
        timed_out=record.timed_out,
        returncode=record.sandbox_returncode,
    )


def _render_run_results() -> None:
    results = st.session_state.get(K_RUN_RESULTS)
    if results is None:
        return
    st.divider()
    st.markdown("**Run results**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Records in", results["input_count"])
    c2.metric("Records out", results["output_count"])
    c3.metric("Errors", len(results["issues"]))
    st.caption(
        "Tasks applied: " + ", ".join(f"`{n}`" for n in results["ran_tasks"])
    )

    if results.get("timed_out"):
        st.error(
            "Sandbox hit the wall-clock limit. Output may be partial. "
            "Reduce the batch size or split the task into smaller steps."
        )
    elif results.get("sandbox_returncode", 0) != 0:
        st.warning(
            f"Sandbox exited with code {results['sandbox_returncode']}. "
            "Check the error table below."
        )

    if results["issues"]:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "record": str(i.record_index) if i.record_index else "—",
                        "identifier": i.identifier or "—",
                        "task": i.task or "—",
                        "code": i.code,
                        "message": i.message,
                    }
                    for i in results["issues"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    # Pre-download diff review — surfaces what actually changed so the
    # cataloger can verify the task did the expected work before
    # exporting.
    _render_diff_review(results)

    st.markdown("**Updated task output is ready as a separate export.**")
    st.caption(_history_location_caption(results.get("snapshot_id")))
    _offer_history_download(
        st,
        results.get("out_path"),
        f"Download {results['out_filename']}",
        results["out_filename"],
        key="tasks_download",
    )


def _render_run_history() -> None:
    """Render the per-session Tasks run history (TASK-034).

    Collapsed expander listing the last :data:`run_history.DEFAULT_HISTORY_CAP`
    runs (newest first). Each entry shows summary metadata + two
    download buttons that read input/output bytes from disk on click,
    so a long session with several 100K-batch runs doesn't pin all
    that data in Python memory.
    """
    history: list[TaskRunRecord] = st.session_state.get(
        "task_run_history"
    ) or []
    if not history:
        return

    with st.expander(
        f"Run history (last {len(history)} of "
        f"{run_history.DEFAULT_HISTORY_CAP})",
        expanded=False,
    ):
        st.caption(
            "Per-session log of Tasks runs. Closing the tab discards it; "
            "see the audit log for the durable record."
        )
        # Newest first.
        for record in reversed(history):
            _render_history_entry(record)


def _render_persisted_job_snapshots() -> None:
    """Render durable job-scoped snapshots for rollback across sessions."""
    job_id = st.session_state.get("current_job_id")
    if job_id is None:
        return
    rows = provenance.list_snapshots(int(job_id))
    if not rows:
        return

    with st.expander(f"Job snapshots ({len(rows)})", expanded=False):
        st.caption(
            "Durable before/after snapshots for this job. Restoring loads the "
            "pre-change version back into the current session."
        )
        for row in rows:
            _render_job_snapshot_entry(row)


def _render_job_snapshot_entry(row: dict) -> None:
    summary = _snapshot_summary(row)
    st.markdown(
        f"**{row['created_at']}** — `{row['kind']}` — "
        f"{row['label'] or '(no label)'}"
    )
    st.caption(f"By {row['user_email']}" + (f" · {summary}" if summary else ""))

    cols = st.columns(3)
    if cols[0].button(
        "Restore pre-change version",
        key=f"snapshot_restore_{row['id']}",
        help="Replace the current loaded batch with this snapshot's before state.",
    ):
        raw = provenance.restore_bytes(int(row["id"]))
        filename = session.current_filename() or f"snapshot-{row['id']}.mrc"
        session.replace_current_store_from_bytes(
            raw,
            filename=filename,
            job_id=int(row["job_id"]),
        )
        audit_event(
            "job-snapshot-restored",
            user=session.current_user_id(),
            snapshot_id=row["id"],
            job_id=row["job_id"],
            snapshot_kind=row["kind"],
        )
        st.success("Restored the pre-change version into the current session.")
        st.rerun()

    _offer_history_download(
        cols[1],
        row.get("before_path"),
        "Download before",
        f"snapshot_{row['id']}_before.mrc",
        key=f"snapshot_before_{row['id']}",
    )
    _offer_history_download(
        cols[2],
        row.get("after_path"),
        "Download after",
        f"snapshot_{row['id']}_after.mrc",
        key=f"snapshot_after_{row['id']}",
    )
    st.divider()


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


def _render_history_entry(record: TaskRunRecord) -> None:
    """Render one TaskRunRecord row in the history expander."""
    status_emoji = (
        "⚠️" if record.timed_out or record.sandbox_returncode != 0 else "✅"
    )
    tasks_label = ", ".join(f"`{n}`" for n in record.task_names) or "(none)"
    st.markdown(
        f"{status_emoji} **{record.timestamp}** — "
        f"`{record.input_filename or 'no-file'}` — {tasks_label}"
    )

    cols = st.columns(4)
    cols[0].metric("In", record.input_record_count)
    cols[1].metric("Out", record.output_record_count)
    cols[2].metric("Errors", record.error_count)
    cols[3].metric(
        "Exit",
        "timeout" if record.timed_out else str(record.sandbox_returncode),
    )

    btn_cols = st.columns(2)
    _offer_history_download(
        btn_cols[0],
        record.input_path,
        f"⬇ Re-download input ({record.timestamp})",
        f"input_{record.timestamp.replace(':', '')}.mrc",
        key=f"history_in_{record.timestamp}",
    )
    _offer_history_download(
        btn_cols[1],
        record.output_path,
        f"⬇ Re-download output ({record.timestamp})",
        f"output_{record.timestamp.replace(':', '')}.mrc",
        key=f"history_out_{record.timestamp}",
    )
    st.divider()


def _offer_history_download(
    column,
    path_str: str | None,
    label: str,
    file_name: str,
    *,
    key: str,
) -> None:
    """Render a two-step prepare → download for a historical file.

    TASK-035 fix: Streamlit's ``download_button`` materializes its
    ``data`` argument eagerly, and Streamlit re-runs expander
    contents even when collapsed. Reading every history row's bytes
    on every Tasks-page render would pin hundreds of MB for a
    long-running session.

    The fix: the first render shows a "Prepare download" button.
    Clicking it sets a per-row ready flag in session_state; the next
    render reads the file's bytes once and renders the actual
    ``download_button``. If the workdir is gone (container restart,
    cleanup), the row degrades to a disabled button explaining why.
    """
    if not path_str:
        column.caption("(no file recorded)")
        return
    path = Path(path_str)
    if not path.exists():
        column.button(
            label, disabled=True,
            help="Sandbox workdir is gone — input/output is no longer available.",
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


def _render_diff_review(results: dict) -> None:
    """Render the post-run diff review (summary + per-record drill-down).

    The diff is computed when the task completes. Rendering does not
    rebuild it from output bytes because that would re-read large MARC
    files on ordinary page refreshes.
    """
    input_path_str = results.get("sandbox_input_path")
    out_path_str = results.get("out_path")
    if not input_path_str or not out_path_str:
        return
    input_path = Path(input_path_str)
    out_path = Path(out_path_str)
    if not input_path.exists() or not out_path.exists():
        # Sandbox workdir was cleaned out (container restart, ops
        # cleanup). Nothing we can do — the user can re-run.
        return

    summary = results.get("_diff_summary")
    if summary is None:
        return

    st.divider()
    st.markdown("**Review changes before download**")

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

    _render_per_tag_summary_table(summary)

    if summary.changed_count == 0:
        st.info(
            "The tasks ran without modifying any records — verify the "
            "task body matches the records you expected to touch."
        )
        return

    cap_note = ""
    if summary.cap_triggered:
        cap_note = (
            f" — showing first **{len(summary.per_record_diffs)}** of "
            f"**{summary.changed_count}** (rest summarized above)"
        )
    with st.expander(
        f"Show per-record diffs ({summary.changed_count} record"
        f"{'s' if summary.changed_count != 1 else ''}){cap_note}",
        expanded=False,
    ):
        _render_per_record_diffs(summary)


def _render_per_tag_summary_table(summary: task_diff.TaskDiffSummary) -> None:
    """Tag / Added / Deleted / Modified rollup table."""
    tags = sorted(
        set(summary.per_tag_added)
        | set(summary.per_tag_deleted)
        | set(summary.per_tag_modified)
    )
    if not tags:
        return
    df = pd.DataFrame(
        [
            {
                "Tag": t,
                "Added": summary.per_tag_added.get(t, 0),
                "Deleted": summary.per_tag_deleted.get(t, 0),
                "Modified": summary.per_tag_modified.get(t, 0),
            }
            for t in tags
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)


_DIFF_PAGE_KEY = "tasks_diff_page"
_DIFF_PER_PAGE = 5


def _render_per_record_diffs(summary: task_diff.TaskDiffSummary) -> None:
    """Paginated side-by-side per-record diff cards."""
    diffs = summary.per_record_diffs
    total = len(diffs)
    pages = max(1, (total + _DIFF_PER_PAGE - 1) // _DIFF_PER_PAGE)
    page = st.session_state.get(_DIFF_PAGE_KEY, 0)
    page = max(0, min(page, pages - 1))

    nav_a, nav_b, nav_c = st.columns([1, 2, 1])
    if nav_a.button("◀ Prev", key="tasks_diff_prev", disabled=page == 0):
        st.session_state[_DIFF_PAGE_KEY] = page - 1
        st.rerun()
    nav_b.caption(f"Page {page + 1} of {pages} — {total} changed records")
    if nav_c.button("Next ▶", key="tasks_diff_next", disabled=page >= pages - 1):
        st.session_state[_DIFF_PAGE_KEY] = page + 1
        st.rerun()

    start = page * _DIFF_PER_PAGE
    end = min(total, start + _DIFF_PER_PAGE)
    for diff in diffs[start:end]:
        st.markdown(
            f"**Record {diff.record_index + 1}** "
            + (f"— `001 = {diff.identifier}`" if diff.identifier else "")
        )
        _render_diff_rows(diff.rows)
        st.divider()


_STATUS_SYMBOL = {
    "unchanged": "  ",
    "added":     "+ ",
    "removed":   "- ",
    "changed":   "~ ",
}


def _render_diff_rows(
    rows: list[tuple[str, str, "marc_diff.DiffStatus"]],  # noqa: F821
) -> None:
    """Side-by-side rendering of one record's aligned diff.

    Uses a code block per side to preserve monospaced field-line
    alignment. Status markers (+, -, ~, " ") on each line make
    skim-reading easy without needing colors.
    """
    left_lines: list[str] = []
    right_lines: list[str] = []
    for old, new, status in rows:
        sym = _STATUS_SYMBOL[status]
        # Show the symbol on the side(s) where it makes sense.
        left_lines.append(
            f"{sym if status in ('removed', 'changed') else '  '}{old}"
        )
        right_lines.append(
            f"{sym if status in ('added', 'changed') else '  '}{new}"
        )
    col_old, col_new = st.columns(2)
    col_old.caption("Before")
    col_old.code("\n".join(left_lines), language="text")
    col_new.caption("After")
    col_new.code("\n".join(right_lines), language="text")


def _stamped_filename(orig: str | None) -> str:
    return _export_filename(orig, "transformed")


def _export_filename(orig: str | None, operation: str) -> str:
    if not orig:
        return session.stamped_filename(f"transformed_{operation}")
    p = Path(orig)
    return session.stamped_filename(f"{p.stem}_{operation}", p.suffix or ".mrc")


def _disk_backed_export(
    *,
    filename: str,
    data: bytes,
    snapshot: dict | None,
    prefix: str,
) -> dict:
    snapshot_path = snapshot.get("after_path") if snapshot else None
    if snapshot_path and Path(snapshot_path).exists():
        path = Path(snapshot_path)
        temporary_dir = None
        temporary = False
    else:
        export_dir = Path(tempfile.mkdtemp(prefix=prefix))
        path = export_dir / filename
        path.write_bytes(data)
        temporary_dir = str(export_dir)
        temporary = True
    return {
        "filename": filename,
        "path": str(path),
        "temporary": temporary,
        "temporary_dir": temporary_dir,
        "snapshot_id": snapshot["id"] if snapshot is not None else None,
    }


def _cleanup_disk_backed_export(export: dict | None) -> None:
    if not export or not export.get("temporary"):
        return
    path_str = export.get("path")
    if path_str:
        try:
            Path(path_str).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not remove temporary export file: %s", exc)
    temp_dir = export.get("temporary_dir")
    if temp_dir:
        try:
            Path(temp_dir).rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# TASK-036: Quick find/replace wizard
# ---------------------------------------------------------------------------


_K_BR_PREVIEW = "batch_replace_preview"


def _render_quick_find_replace() -> None:
    """Render the one-shot find/replace wizard.

    Mounted below the saved-tasks run panel. Cataloger fills the
    form, clicks Preview, reviews the diff, clicks Apply.
    The wizard never persists a task file; the body lives only
    inside the sandbox driver's exec call.
    """
    if not session.has_upload():
        return  # nothing to find against

    with st.expander("✨ Quick find/replace", expanded=True):
        st.caption(
            "Run a one-shot find/replace across the loaded batch. "
            "Preview first; apply after you've reviewed the diff. "
            "Nothing is saved to your task list."
        )

        c1, c2 = st.columns([2, 1])
        tag = c1.text_input(
            "Tag (required)",
            value=st.session_state.get("br_tag", ""),
            max_chars=3,
            placeholder="245",
            key="br_tag",
        )
        subfield = c2.text_input(
            "Subfield (optional)",
            value=st.session_state.get("br_subfield", ""),
            max_chars=1,
            placeholder="a",
            help=(
                "Restrict the replace to one subfield code. Leave blank "
                "to replace across every subfield value of the tag."
            ),
            key="br_subfield",
        )

        find_text = st.text_input(
            "Find",
            value=st.session_state.get("br_find", ""),
            key="br_find",
        )
        replace_text = st.text_input(
            "Replace with",
            value=st.session_state.get("br_replace", ""),
            key="br_replace",
        )

        opt_a, opt_b = st.columns(2)
        regex = opt_a.checkbox(
            "Treat Find as regex",
            value=st.session_state.get("br_regex", False),
            key="br_regex",
        )
        ignore_case = opt_b.checkbox(
            "Case-insensitive",
            value=st.session_state.get("br_ignore_case", False),
            key="br_ignore_case",
        )

        request = BatchReplaceRequest(
            tag=(tag or "").strip(),
            subfield=(subfield or None) or None,
            find=find_text or "",
            replace=replace_text or "",
            regex=bool(regex),
            ignore_case=bool(ignore_case),
        )

        btn_preview, btn_reset, _ = st.columns([1, 1, 4])
        if btn_preview.button(
            "Preview", type="primary", key="br_preview_btn",
        ):
            _build_and_store_preview(request)
        if btn_reset.button("Reset", key="br_reset_btn"):
            st.session_state.pop(_K_BR_PREVIEW, None)
            st.rerun()

        preview = st.session_state.get(_K_BR_PREVIEW)
        if preview is not None:
            _render_quick_preview(preview)


def _build_and_store_preview(request: BatchReplaceRequest) -> None:
    """Validate, run the sandbox preview, stash the result in session_state."""
    err = batch_replace.validate_request(request)
    if err:
        st.error(err)
        return

    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload a `.mrc` on Home first.")
        return

    with st.spinner("Building preview…"):
        try:
            preview = batch_replace.build_preview(store, request)
        except ValueError as exc:
            st.error(str(exc))
            return

    st.session_state.pop(_K_QB_PREVIEW, None)
    st.session_state[_K_BR_PREVIEW] = preview


def _render_quick_preview(preview) -> None:
    st.divider()
    if preview.error:
        st.error(preview.error)
        return
    if preview.is_empty:
        st.info(
            f"No records matched the find criteria "
            f"(tag={preview.request.tag!r}, "
            f"subfield={preview.request.subfield!r}, "
            f"find={preview.request.find!r})."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Matched", len(preview.matched_indices))
    c2.metric("Changed (in preview)", preview.changed_count)
    c3.metric(
        "Previewed records",
        len(preview.output_records),
    )

    if preview.preview_cap_triggered:
        st.info(
            f"Sandbox preview ran against the first "
            f"**{len(preview.output_records):,}** of "
            f"**{len(preview.matched_indices):,}** matched records. "
            "Apply will run a fresh sandbox over the full matched set "
            "before committing — review the diff below to spot-check "
            "what the transform does."
        )

    if preview.diff_summary is not None and preview.diff_summary.per_record_diffs:
        # Reuse the existing per-tag rollup + per-record drill-down
        # used by the saved-task run results so the cataloger sees a
        # familiar review surface.
        _render_per_tag_summary_table(preview.diff_summary)
        with st.expander(
            f"Show per-record diffs ({preview.changed_count} changed records)",
            expanded=False,
        ):
            _render_per_record_diffs(preview.diff_summary)

    apply_col, _, _ = st.columns([1, 1, 4])
    if apply_col.button(
        "Apply to batch", type="primary", key="br_apply_btn",
    ):
        _apply_quick_preview(preview)


def _apply_quick_preview(preview) -> None:
    """Run apply, audit, refresh derived caches."""
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return
    before_bytes = store.to_mrc_bytes()
    result = batch_replace.apply_preview(store, preview)
    if result.error:
        st.error(result.error)
        if result.stale_indices:
            st.caption(
                "Stale indices (1-based): "
                + ", ".join(str(i + 1) for i in result.stale_indices)
            )
        return

    user = session.current_user_id()
    label = f"Find/replace {preview.request.tag}"
    if preview.request.subfield:
        label += f"${preview.request.subfield}"
    try:
        snapshot = snapshot_actions.record_job_snapshot(
            job_id=st.session_state.get("current_job_id"),
            user_email=user,
            kind="quick-replace",
            label=label,
            before_bytes=before_bytes,
            after_bytes=store.to_mrc_bytes(),
            summary={
                "matched_count": len(preview.matched_indices),
                "changed_count": preview.changed_count,
                "applied_count": len(result.applied_indices),
            },
        )
    except Exception:  # noqa: BLE001 — snapshot loss must not block the apply
        logger.exception("quick find/replace snapshot failed")
        snapshot = None
        st.warning(
            "Change applied, but recording the history snapshot failed."
        )
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=user,
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )

    audit_event(
        "batch-replace-applied",
        user=user,
        filename=session.current_filename(),
        tag=preview.request.tag,
        subfield=preview.request.subfield,
        regex=preview.request.regex,
        ignore_case=preview.request.ignore_case,
        matched_count=len(preview.matched_indices),
        changed_count=preview.changed_count,
        applied_count=len(result.applied_indices),
    )
    # Stale derived state — Validate / Report / etc. cached the
    # pre-apply numbers.
    st.session_state["issues_cache"] = {}
    st.session_state.pop(_K_BR_PREVIEW, None)
    st.success(
        f"Applied to {len(result.applied_indices)} record(s). "
        "Other records are unchanged."
    )
    st.rerun()


# ---------------------------------------------------------------------------
# TASK-137: Quick batch operation wizard
# ---------------------------------------------------------------------------


_K_QB_PREVIEW = "quick_batch_preview"
_K_QB_EXPORT = "quick_batch_export"

_QB_OPERATION_LABELS = {
    "leader": "Leader value",
    "008-form": "008 form of item",
    "040-cleanup": "040 cleanup",
    "856-url": "856 URL tools",
    "035-oclc": "OCLC 035 cleanup",
    "9xx-delete": "Local 9xx cleanup",
    "655-cleanup": "655 genre/form cleanup",
}

_QB_856_ACTION_LABELS = {
    "add-proxy": "Add proxy prefix",
    "remove-proxy": "Remove proxy prefix",
    "delete-matching": "Delete 856 fields by URL text",
}


def _render_quick_batch_operations() -> None:
    """Render one-shot canned MARC cleanup operations."""
    if not session.has_upload():
        return

    st.divider()
    with st.expander("Quick batch operations", expanded=True):
        st.caption(
            "Run a structured cleanup across the loaded batch. Preview first; "
            "nothing is saved to your task list."
        )
        kind = st.selectbox(
            "Operation",
            options=list(_QB_OPERATION_LABELS),
            format_func=lambda value: _QB_OPERATION_LABELS.get(value, value),
            key="qb_kind",
        )
        request = _quick_batch_request_from_widgets(kind)

        btn_preview, btn_reset, _ = st.columns([1, 1, 4])
        if btn_preview.button("Preview", type="primary", key="qb_preview_btn"):
            _build_and_store_quick_batch_preview(request)
        if btn_reset.button("Reset", key="qb_reset_btn"):
            st.session_state.pop(_K_QB_PREVIEW, None)
            st.rerun()

        preview = st.session_state.get(_K_QB_PREVIEW)
        if preview is not None:
            _render_quick_batch_preview(preview)
        _render_quick_batch_export()


def _quick_batch_request_from_widgets(kind: str) -> QuickBatchRequest:
    if kind == "leader":
        positions = list(quick_batch.LEADER_OPTIONS)
        position = st.selectbox(
            "Leader position",
            options=positions,
            format_func=_format_leader_position,
            key="qb_leader_position",
        )
        options = quick_batch.LEADER_OPTIONS[position]
        value = st.selectbox(
            "Value",
            options=[option.value for option in options],
            format_func=lambda code: _format_code_option(code, options),
            key="qb_leader_value",
        )
        return QuickBatchRequest(kind=kind, position=position, value=value)

    if kind == "008-form":
        value = st.selectbox(
            "Form of item",
            options=[option.value for option in quick_batch.FORM_OF_ITEM_OPTIONS],
            format_func=lambda code: _format_code_option(
                code,
                quick_batch.FORM_OF_ITEM_OPTIONS,
            ),
            key="qb_008_form",
        )
        return QuickBatchRequest(kind=kind, value=value)

    if kind == "040-cleanup":
        agency = st.text_input(
            "Cataloging agency for 040 $d",
            value=st.session_state.get("qb_040_agency", ""),
            key="qb_040_agency",
        )
        return QuickBatchRequest(kind=kind, agency=agency)

    if kind == "856-url":
        action = st.selectbox(
            "856 URL action",
            options=list(_QB_856_ACTION_LABELS),
            format_func=lambda value: _QB_856_ACTION_LABELS.get(value, value),
            key="qb_856_action",
        )
        url_contains = st.text_input(
            "URL contains",
            value=st.session_state.get("qb_856_contains", ""),
            key="qb_856_contains",
        )
        proxy_prefix = ""
        if action in {"add-proxy", "remove-proxy"}:
            proxy_prefix = st.text_input(
                "Proxy prefix",
                value=st.session_state.get("qb_856_proxy_prefix", ""),
                key="qb_856_proxy_prefix",
            )
        return QuickBatchRequest(
            kind=kind,
            action=action,
            url_contains=url_contains,
            proxy_prefix=proxy_prefix,
        )

    if kind == "035-oclc":
        st.caption("Normalizes OCLC-style 035 $a/$z values and leaves 035 $9 alone.")
        return QuickBatchRequest(kind=kind)

    if kind == "9xx-delete":
        tag = st.text_input(
            "Tag to delete",
            value=st.session_state.get("qb_9xx_tag", "9XX"),
            max_chars=3,
            key="qb_9xx_tag",
        )
        return QuickBatchRequest(kind=kind, tag=tag)

    genre_term = st.text_input(
        "655 $a term",
        value=st.session_state.get("qb_655_term", "Electronic books."),
        key="qb_655_term",
    )
    genre_source = st.text_input(
        "655 $2 source",
        value=st.session_state.get("qb_655_source", "lcgft"),
        key="qb_655_source",
    )
    unwanted_text = st.text_input(
        "Remove existing 655 fields containing",
        value=st.session_state.get("qb_655_unwanted", ""),
        key="qb_655_unwanted",
    )
    return QuickBatchRequest(
        kind=kind,
        genre_term=genre_term,
        genre_source=genre_source,
        unwanted_text=unwanted_text,
    )


def _build_and_store_quick_batch_preview(request: QuickBatchRequest) -> None:
    err = quick_batch.validate_request(request)
    if err:
        st.error(err)
        return

    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload a `.mrc` on Home first.")
        return

    on_progress, progress, status = _quick_batch_progress("Previewing")

    with st.spinner("Building preview…"):
        preview = quick_batch.build_preview(store, request, progress=on_progress)
    progress.empty()
    status.empty()
    st.session_state.pop(_K_BR_PREVIEW, None)
    st.session_state[_K_QB_PREVIEW] = preview


def _render_quick_batch_preview(preview) -> None:
    st.divider()
    if preview.error:
        st.error(preview.error)
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Records", len(preview.output_records))
    c2.metric("Changed", preview.changed_count)
    c3.metric("Unchanged", preview.skipped_count)

    if preview.changed_count == 0:
        st.info("This operation would not change the loaded batch.")
        return

    if preview.detail_counts:
        rows = [
            {"Detail": detail, "Count": count}
            for detail, count in sorted(preview.detail_counts.items())
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    apply_col, _, _ = st.columns([1, 1, 4])
    if apply_col.button(
        "Apply to batch",
        type="primary",
        key="qb_apply_btn",
    ):
        _apply_quick_batch_preview(preview)


def _apply_quick_batch_preview(preview) -> None:
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return
    record_count = len(preview.output_records)
    on_progress, progress, status = _quick_batch_progress("Checking")
    before_bytes = store.to_mrc_bytes()

    with st.spinner(
        f"Applying quick batch operation to {record_count:,} record"
        f"{'s' if record_count != 1 else ''}…"
    ):
        result = quick_batch.apply_preview(store, preview, progress=on_progress)
    progress.empty()
    status.empty()
    if result.error:
        st.error(result.error)
        return
    after_bytes = store.to_mrc_bytes()
    export_filename = _export_filename(session.current_filename(), "quickbatch")
    snapshot = snapshot_actions.record_job_snapshot(
        job_id=st.session_state.get("current_job_id"),
        user_email=session.current_user_id(),
        kind="quick-batch",
        label=_QB_OPERATION_LABELS.get(preview.request.kind, preview.request.kind),
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        summary={
            "operation_kind": preview.request.kind,
            "changed_count": result.changed_count,
            "skipped_count": result.skipped_count,
            "export_filename": export_filename,
        },
    )
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=session.current_user_id(),
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )

    audit_event(
        "quick-batch-applied",
        user=session.current_user_id(),
        filename=session.current_filename(),
        operation_kind=preview.request.kind,
        changed_count=result.changed_count,
        skipped_count=result.skipped_count,
    )
    st.session_state["issues_cache"] = {}
    st.session_state.pop(_K_QB_PREVIEW, None)
    st.session_state.pop(K_QB_DOWNLOAD_READY, None)
    _cleanup_disk_backed_export(st.session_state.get(_K_QB_EXPORT))
    st.session_state[_K_QB_EXPORT] = _disk_backed_export(
        filename=export_filename,
        data=after_bytes,
        snapshot=snapshot,
        prefix="marcedit-web-quickbatch-",
    )
    st.success(
        f"Applied quick batch operation to {result.changed_count} record(s)."
    )
    st.rerun()


def _render_quick_batch_export() -> None:
    export = st.session_state.get(_K_QB_EXPORT)
    if not export:
        return
    st.markdown("**Updated batch is loaded in this session.**")
    if export.get("snapshot_id"):
        st.caption(_history_location_caption(export.get("snapshot_id")))
    else:
        st.caption(_history_location_caption(None))
    path_str = export.get("path")
    if not path_str:
        st.caption("Updated export file is not available in this session.")
        return
    path = Path(path_str)
    if not path.exists():
        st.button(
            "Download updated MARC",
            disabled=True,
            help="The temporary export file is no longer available.",
            key="quick_batch_download_missing",
        )
        return
    if not st.session_state.get(K_QB_DOWNLOAD_READY):
        if st.button(
            "Prepare Download updated MARC",
            key="quick_batch_prepare_download",
            help=(
                "Loads the updated MARC file from disk and offers a "
                "download button. This avoids re-reading large files on "
                "every page refresh."
            ),
        ):
            st.session_state[K_QB_DOWNLOAD_READY] = True
            st.rerun()
        return

    st.download_button(
        label="Download updated MARC",
        data=path.read_bytes(),
        file_name=export["filename"],
        mime="application/marc",
        key="quick_batch_download_updated",
    )


def _quick_batch_progress(verb: str, *, min_step: int = 250):
    progress = st.progress(0.0)
    status = st.empty()
    last_rendered = 0

    def on_progress(processed: int, total: int) -> None:
        nonlocal last_rendered
        if total <= 0:
            return
        if (
            processed != 1
            and processed != total
            and processed % min_step != 0
            and processed - last_rendered < min_step
        ):
            return
        last_rendered = processed
        progress.progress(processed / total)
        status.markdown(f"{verb} record {processed:,} of {total:,}…")

    return on_progress, progress, status


def _history_location_caption(snapshot_id) -> str:
    if snapshot_id:
        return (
            "Rollback and before/after downloads are available under Job "
            "snapshots on this Tasks page."
        )
    return (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )


def _format_leader_position(position: str) -> str:
    labels = {
        "05": "05 — Record status",
        "06": "06 — Type of record",
        "07": "07 — Bibliographic level",
        "08": "08 — Type of control",
        "17": "17 — Encoding level",
        "18": "18 — Descriptive cataloging form",
        "19": "19 — Multipart resource record level",
    }
    return labels.get(position, position)


def _format_code_option(value: str, options) -> str:
    labels = {option.value: option.label for option in options}
    display = "blank" if value == " " else repr(value)
    return f"{display} — {labels.get(value, value)}"
