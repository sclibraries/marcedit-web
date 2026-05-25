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

Storage is still per-user filesystem (Stage 12); tasks survive across
sessions under ``data/tasks/users/<safe-eppn>/``.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    editor,
    marcedit_import,
    quotas,
    run_history,
    sandbox,
    session,
    task_admin,
    task_builder,
    task_diff,
    task_storage,
    tasks,
)
from marcedit_web.lib.audit import audit_event
from marcedit_web.lib.run_history import TaskRunRecord
from marcedit_web.lib.errors import Issue, transform_issue
from marcedit_web.lib.task_builder import OPERATIONS_PALETTE, Operation

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
K_EDITOR_NAME_INPUT = "tasks_editor_name_input"
K_EDITOR_DESCRIPTION_INPUT = "tasks_editor_description_input"
K_RUN_RESULTS = "tasks_run_results"
K_SAVE_ERROR = "tasks_save_error"
K_SAVE_SUCCESS = "tasks_save_success"


def render() -> None:
    """Render the Tasks tab into the current Streamlit container."""
    current_user_id = st.session_state.get("user", "anonymous") or "anonymous"
    is_admin = task_admin.is_admin(current_user_id)
    tasks_dir = task_storage.user_tasks_dir(current_user_id)

    # Editor draft state — namespaced.
    st.session_state.setdefault(K_EDITOR_OPEN, False)
    st.session_state.setdefault(K_EDITOR_MODE, "form")  # "form" | "code"
    st.session_state.setdefault(K_EDITOR_NAME, "")
    st.session_state.setdefault(K_EDITOR_DESCRIPTION, "")
    st.session_state.setdefault(K_EDITOR_BODY, "")
    st.session_state.setdefault(K_EDITOR_OPS, [])  # list[dict] — Operation.to_dict()
    st.session_state.setdefault(K_EDITOR_ORIGINAL_NAME, None)
    st.session_state.setdefault(K_RUN_RESULTS, None)

    # Load shared first then user — user-named tasks shadow shared ones.
    for _d in task_storage.visible_task_dirs(current_user_id):
        tasks.load_user_tasks(_d, force_reload=False)
    registered = tasks.all_tasks()

    # --- Counts banner + admin badge --------------------------------------

    user_task_files = sorted(p.stem for p in tasks_dir.glob("*.py"))
    shared_task_files = sorted(
        p.stem for p in task_storage.shared_tasks_dir().glob("*.py")
    )
    cnt_a, cnt_b, cnt_c, cnt_d = st.columns([2, 2, 2, 2])
    cnt_a.metric("Yours", len(user_task_files))
    cnt_b.metric("Shared", len(shared_task_files))
    cnt_c.metric("Registered", len(registered))
    if cnt_d.button("Clear my tasks", key="tasks_clear_mine"):
        for fname in user_task_files:
            name = fname.replace("_", "-")
            try:
                editor.delete_user_task(tasks_dir, name)
                tasks.TASK_REGISTRY.pop(name, None)
            except Exception as exc:  # noqa: BLE001
                logger.exception("delete_user_task failed for %s", name)
                st.warning(f"Could not delete {name}: {exc}")
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
    if not registered:
        st.info(
            "No tasks defined yet. Use **+ New task** below or **Import "
            "from MarcEdit** to convert an existing `.tasksfile`."
        )
    else:
        for entry in registered:
            cols = st.columns([3, 5, 1, 1])
            cols[0].markdown(f"**`{entry.name}`**")
            cols[1].caption(entry.description or "_(no description)_")
            if cols[2].button("Edit", key=f"edit_{entry.name}"):
                _open_editor_for_existing(entry, tasks_dir, is_admin)
                st.rerun()
            if cols[3].button("Delete", key=f"del_{entry.name}"):
                editor.delete_user_task(tasks_dir, entry.name)
                tasks.TASK_REGISTRY.pop(entry.name, None)
                audit_event(
                    "task-deleted",
                    user=current_user_id,
                    task_name=entry.name,
                )
                st.rerun()

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

    # --- Editor (form or code) --------------------------------------------

    if st.session_state[K_EDITOR_OPEN]:
        _render_editor(tasks_dir, is_admin)

    # --- Run on loaded batch (sandbox path) -------------------------------

    st.divider()
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
        st.info("Create or import at least one task above to enable running.")
    else:
        _render_run_panel(registered, tasks_dir)

    _render_run_results()
    _render_run_history()


# ---------------------------------------------------------------------------
# Editor state helpers
# ---------------------------------------------------------------------------


def _open_editor_for_new() -> None:
    """Open the editor for a brand-new task in form mode."""
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_MODE] = "form"
    st.session_state[K_EDITOR_NAME] = ""
    st.session_state[K_EDITOR_DESCRIPTION] = ""
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


def _open_editor_for_existing(
    entry, tasks_dir: Path, is_admin: bool,
) -> None:
    """Open the editor pre-populated from an on-disk task file."""
    try:
        parsed = editor.parse_user_task_file(
            editor.task_file_path(tasks_dir, entry.name)
        )
    except ValueError as exc:
        st.error(f"Could not open {entry.name}: {exc}")
        return

    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_NAME] = parsed["name"]
    st.session_state[K_EDITOR_DESCRIPTION] = parsed["description"]
    st.session_state[K_EDITOR_BODY] = parsed["body"]
    st.session_state[K_EDITOR_ORIGINAL_NAME] = parsed["name"]

    parse_result = task_builder.parse_ops_from_source(parsed["body"])
    if parse_result["form_editable"]:
        st.session_state[K_EDITOR_MODE] = "form"
        st.session_state[K_EDITOR_OPS] = [
            op.to_dict() for op in parse_result["ops"]
        ]
    else:
        # Hand-written: code mode if admin, else read-only-style notice.
        st.session_state[K_EDITOR_MODE] = "code" if is_admin else "form"
        st.session_state[K_EDITOR_OPS] = []


def _do_marcedit_import(upl, tasks_dir: Path) -> None:
    """Import a MarcEdit `.tasksfile` or `.task` archive into tasks_dir."""
    user = st.session_state.get("user", "anonymous") or "anonymous"
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
            tmp_path = tasks_dir / f".__import__{upl.name}"
            tmp_path.write_bytes(raw)
            archive = marcedit_import.convert_task_archive(tmp_path)
            tmp_path.unlink(missing_ok=True)
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
                    content = marcedit_import.build_full_task_file(er.conversion)
                    path = editor.task_file_path(tasks_dir, er.conversion.name)
                    path.write_text(content)
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
            content = marcedit_import.build_full_task_file(conv)
            path = editor.task_file_path(tasks_dir, conv.name)
            path.write_text(content)
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

    if st.session_state[K_EDITOR_MODE] == "form":
        _render_form_editor()
    else:
        _render_code_editor()

    save_col, cancel_col = st.columns([1, 1])
    save_col.button(
        "Save task",
        type="primary",
        key="tasks_save",
        on_click=_save_callback,
        args=(tasks_dir,),
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
        st.session_state.get("user", "anonymous") or "anonymous"
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
    dict-changed-size error in `_call_callbacks`."""
    name = (st.session_state.get(K_EDITOR_NAME_INPUT)
            or st.session_state.get(K_EDITOR_NAME) or "").strip()
    description = (
        st.session_state.get(K_EDITOR_DESCRIPTION_INPUT)
        or st.session_state.get(K_EDITOR_DESCRIPTION)
        or ""
    ).strip()
    original = st.session_state.get(K_EDITOR_ORIGINAL_NAME)
    mode = st.session_state.get(K_EDITOR_MODE, "form")

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

    try:
        editor.save_user_task(
            tasks_dir,
            name=name,
            description=description,
            body=body,
            original_name=original,
            extra_imports=extra_imports,
        )
    except ValueError as exc:
        st.session_state[K_SAVE_ERROR] = str(exc)
        return

    if original and original != name:
        tasks.TASK_REGISTRY.pop(original, None)
    tasks.TASK_REGISTRY.pop(name, None)
    tasks.load_user_tasks(tasks_dir, force_reload=True)
    st.session_state[K_EDITOR_OPEN] = False
    st.session_state[K_SAVE_SUCCESS] = f"Saved `{name}`."
    user = st.session_state.get("user", "anonymous") or "anonymous"
    is_admin = task_admin.is_admin(user)
    audit_event(
        "task-saved",
        user=user,
        task_name=name,
        original=original,
        mode=mode,
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

    user = st.session_state.get("user", "anonymous") or "anonymous"
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

    st.session_state[K_RUN_RESULTS] = {
        "issues": issues,
        "out_bytes": result.records_bytes,
        "out_filename": _stamped_filename(session.current_filename()),
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

    st.download_button(
        label=f"Download {results['out_filename']}",
        data=results["out_bytes"],
        file_name=results["out_filename"],
        mime="application/marc",
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

    Computation is lazy — the diff is built on first render and cached
    in session_state under the run-results key so re-renders (after a
    pagination click, say) reuse the same TaskDiffSummary.
    """
    input_path_str = results.get("sandbox_input_path")
    out_bytes = results.get("out_bytes") or b""
    if not input_path_str or not out_bytes:
        return
    input_path = Path(input_path_str)
    if not input_path.exists():
        # Sandbox workdir was cleaned out (container restart, ops
        # cleanup). Nothing we can do — the user can re-run.
        return

    summary = results.get("_diff_summary")
    if summary is None:
        with st.spinner("Building diff…"):
            summary = task_diff.compute_task_diff(input_path, out_bytes)
        # Stash on the in-memory dict; survives reruns within the
        # session until a new run replaces K_RUN_RESULTS wholesale.
        results["_diff_summary"] = summary

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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not orig:
        return f"transformed_{stamp}.mrc"
    p = Path(orig)
    return f"{p.stem}_{stamp}{p.suffix or '.mrc'}"
