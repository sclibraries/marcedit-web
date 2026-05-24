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
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    editor,
    marcedit_import,
    sandbox,
    session,
    task_admin,
    task_builder,
    task_storage,
    tasks,
)
from marcedit_web.lib.errors import Issue, transform_issue
from marcedit_web.lib.task_builder import OPERATIONS_PALETTE, Operation

logger = logging.getLogger("marcedit_web.render.tasks")


def render() -> None:
    """Render the Tasks tab into the current Streamlit container."""
    current_user_id = st.session_state.get("user", "anonymous") or "anonymous"
    is_admin = task_admin.is_admin(current_user_id)
    tasks_dir = task_storage.user_tasks_dir(current_user_id)

    # Editor draft state — namespaced.
    st.session_state.setdefault("tasks_editor_open", False)
    st.session_state.setdefault("tasks_editor_mode", "form")  # "form" | "code"
    st.session_state.setdefault("tasks_editor_name", "")
    st.session_state.setdefault("tasks_editor_description", "")
    st.session_state.setdefault("tasks_editor_body", "")
    st.session_state.setdefault("tasks_editor_ops", [])  # list[dict] — Operation.to_dict()
    st.session_state.setdefault("tasks_editor_original_name", None)
    st.session_state.setdefault("tasks_run_results", None)

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
        st.session_state["tasks_editor_open"] = False
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

    if st.session_state["tasks_editor_open"]:
        _render_editor(tasks_dir, is_admin)

    # --- Run on loaded batch (sandbox path) -------------------------------

    st.divider()
    st.subheader("Run on loaded batch")

    if not session.has_upload():
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


# ---------------------------------------------------------------------------
# Editor state helpers
# ---------------------------------------------------------------------------


def _open_editor_for_new() -> None:
    """Open the editor for a brand-new task in form mode."""
    st.session_state["tasks_editor_open"] = True
    st.session_state["tasks_editor_mode"] = "form"
    st.session_state["tasks_editor_name"] = ""
    st.session_state["tasks_editor_description"] = ""
    st.session_state["tasks_editor_body"] = (
        "# `record` is a pymarc.Record. Mutate it in place; do not return.\n"
        "# Example: delete every 029 field.\n"
        "#\n"
        "# from marcedit_web.lib.transforms import delete_tags\n"
        "# delete_tags(record, \"029\")\n"
        "pass\n"
    )
    st.session_state["tasks_editor_ops"] = []
    st.session_state["tasks_editor_original_name"] = None


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

    st.session_state["tasks_editor_open"] = True
    st.session_state["tasks_editor_name"] = parsed["name"]
    st.session_state["tasks_editor_description"] = parsed["description"]
    st.session_state["tasks_editor_body"] = parsed["body"]
    st.session_state["tasks_editor_original_name"] = parsed["name"]

    parse_result = task_builder.parse_ops_from_source(parsed["body"])
    if parse_result["form_editable"]:
        st.session_state["tasks_editor_mode"] = "form"
        st.session_state["tasks_editor_ops"] = [
            op.to_dict() for op in parse_result["ops"]
        ]
    else:
        # Hand-written: code mode if admin, else read-only-style notice.
        st.session_state["tasks_editor_mode"] = "code" if is_admin else "form"
        st.session_state["tasks_editor_ops"] = []


def _do_marcedit_import(upl, tasks_dir: Path) -> None:
    """Import a MarcEdit `.tasksfile` or `.task` archive into tasks_dir."""
    try:
        if upl.name.lower().endswith(".task"):
            tmp_path = tasks_dir / f".__import__{upl.name}"
            tmp_path.write_bytes(upl.getvalue())
            archive = marcedit_import.convert_task_archive(tmp_path)
            tmp_path.unlink(missing_ok=True)
            if archive.archive_errors:
                for err in archive.archive_errors:
                    st.error(err)
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
        else:
            name = marcedit_import._derive_name_from_filename(upl.name)
            conv = marcedit_import.convert_tasksfile_text(
                upl.getvalue().decode("utf-8"),
                name=name,
                description_fallback=f"Imported from {upl.name}",
            )
            content = marcedit_import.build_full_task_file(conv)
            path = editor.task_file_path(tasks_dir, conv.name)
            path.write_text(content)
            st.success(f"Imported `{conv.name}` from `{upl.name}`.")
            if conv.unsupported:
                st.warning(
                    f"{len(conv.unsupported)} source line(s) were not "
                    "translated; they appear as `# TODO` comments in the "
                    "imported task body."
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("MarcEdit import failed")
        st.error(f"Import failed: {exc}")


# ---------------------------------------------------------------------------
# Editor renderer (form + code)
# ---------------------------------------------------------------------------


def _render_editor(tasks_dir: Path, is_admin: bool) -> None:
    st.divider()
    is_edit = st.session_state["tasks_editor_original_name"] is not None
    st.subheader(
        f"Edit `{st.session_state['tasks_editor_original_name']}`"
        if is_edit
        else "New task"
    )

    # Mode toggle: admins see it, standard users are pinned to form.
    if is_admin:
        mode = st.radio(
            "Editor mode",
            options=["form", "code"],
            index=0 if st.session_state["tasks_editor_mode"] == "form" else 1,
            horizontal=True,
            key="tasks_editor_mode_radio",
            help=(
                "Code view writes raw Python; form view builds tasks from "
                "a typed operation palette. Both run through the subprocess "
                "sandbox at execution time."
            ),
        )
        st.session_state["tasks_editor_mode"] = mode
    else:
        # Standard users are pinned to form view regardless of state.
        st.session_state["tasks_editor_mode"] = "form"

    st.session_state["tasks_editor_name"] = st.text_input(
        "Task name (lowercase, digits, hyphens)",
        value=st.session_state["tasks_editor_name"],
        help="Used in the @task(...) decorator. Must be unique.",
        key="tasks_editor_name_input",
    )
    st.session_state["tasks_editor_description"] = st.text_input(
        "Description (one sentence)",
        value=st.session_state["tasks_editor_description"],
        key="tasks_editor_description_input",
    )

    if st.session_state["tasks_editor_mode"] == "form":
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
    if st.session_state.get("tasks_save_error"):
        st.error(st.session_state.pop("tasks_save_error"))
    if st.session_state.get("tasks_save_success"):
        st.success(st.session_state.pop("tasks_save_success"))


def _render_code_editor() -> None:
    st.caption(
        "Code view. Write the function **body only**. `record` is a "
        "`pymarc.Record`; import helpers from `marcedit_web.lib.transforms` "
        "as needed."
    )
    new_body = st_ace(
        value=st.session_state["tasks_editor_body"],
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
        st.session_state["tasks_editor_body"] = new_body


def _render_form_editor() -> None:
    """Render the operation-palette form editor.

    The op list lives in ``st.session_state["tasks_editor_ops"]`` as a
    list of dicts (``Operation.to_dict()`` shape). Save converts it
    back to Python via ``task_builder.render_ops_to_python``.
    """
    st.caption(
        "Pick operations from the dropdown below. Each operation runs in "
        "order against every record. See the **operation reference** "
        "expander for what each does."
    )

    ops = st.session_state["tasks_editor_ops"]
    to_remove: list[int] = []

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
                    _render_param_input(param, params, key_prefix=f"op_{i}")

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

    # Add-operation control.
    is_admin = task_admin.is_admin(
        st.session_state.get("user", "anonymous") or "anonymous"
    )
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


def _render_param_input(param: dict, params: dict, *, key_prefix: str) -> None:
    """Render one form widget for one operation parameter."""
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
        # Only reached for the `custom` op, which is admin-only via the
        # add-op dropdown filter above.
        params[name] = st.text_area(
            label, value=str(current or ""),
            help=help_text or "Raw Python; runs in the sandbox.",
            key=key,
            height=200,
        )
    else:
        st.warning(f"Unsupported param type `{ptype}` for {name}.")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _save_callback(tasks_dir: Path) -> None:
    """on_click callback for Save. Runs BEFORE Streamlit's iteration phase
    so mutations of TASK_REGISTRY / session_state don't trip the
    dict-changed-size error in `_call_callbacks`."""
    name = (st.session_state.get("tasks_editor_name_input")
            or st.session_state.get("tasks_editor_name") or "").strip()
    description = (
        st.session_state.get("tasks_editor_description_input")
        or st.session_state.get("tasks_editor_description")
        or ""
    ).strip()
    original = st.session_state.get("tasks_editor_original_name")
    mode = st.session_state.get("tasks_editor_mode", "form")

    if mode == "form":
        ops = [
            Operation.from_dict(op)
            for op in st.session_state.get("tasks_editor_ops", [])
        ]
        rendered = task_builder.render_ops_to_python(ops)
        body = rendered["body"]
        extra_imports = rendered["imports"]
    else:
        body = st.session_state.get("tasks_editor_body", "")
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
        st.session_state["tasks_save_error"] = str(exc)
        return

    if original and original != name:
        tasks.TASK_REGISTRY.pop(original, None)
    tasks.TASK_REGISTRY.pop(name, None)
    tasks.load_user_tasks(tasks_dir, force_reload=True)
    st.session_state["tasks_editor_open"] = False
    st.session_state["tasks_save_success"] = f"Saved `{name}`."


def _cancel_callback() -> None:
    """on_click callback for Cancel. Mirrors the on_click pattern of Save."""
    st.session_state["tasks_editor_open"] = False


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

    record_bytes = store.to_mrc_bytes()
    with st.spinner("Running tasks in sandbox..."):
        result = sandbox.run_tasks_subprocess(specs, record_bytes)

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

    st.session_state["tasks_run_results"] = {
        "issues": issues,
        "out_bytes": result.records_bytes,
        "out_filename": _stamped_filename(session.current_filename()),
        "input_count": store.count(),
        "output_count": len(out_records),
        "ran_tasks": list(selection),
        "timed_out": result.timed_out,
        "sandbox_returncode": result.returncode,
    }


def _render_run_results() -> None:
    results = st.session_state.get("tasks_run_results")
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

    st.download_button(
        label=f"Download {results['out_filename']}",
        data=results["out_bytes"],
        file_name=results["out_filename"],
        mime="application/marc",
        key="tasks_download",
    )


def _stamped_filename(orig: str | None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not orig:
        return f"transformed_{stamp}.mrc"
    p = Path(orig)
    return f"{p.stem}_{stamp}{p.suffix or '.mrc'}"
