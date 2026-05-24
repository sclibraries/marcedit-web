"""Tasks tab — list / create / import / run tasks against the loaded batch.

Storage is per-user filesystem (Stage 12); tasks survive across sessions
under `data/tasks/users/<safe-eppn>/` plus a shared `data/tasks/shared/`
library readable by everyone.
"""

from __future__ import annotations

import copy
import io
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import editor, marcedit_import, session, task_storage, tasks
from marcedit_web.lib.errors import Issue, transform_issue

logger = logging.getLogger("marcedit_web.render.tasks")


def render() -> None:
    """Render the Tasks tab into the current Streamlit container."""
    current_user_id = st.session_state.get("user", "anonymous") or "anonymous"
    tasks_dir = task_storage.user_tasks_dir(current_user_id)

    # Editor draft state — namespaced.
    st.session_state.setdefault("tasks_editor_open", False)
    st.session_state.setdefault("tasks_editor_name", "")
    st.session_state.setdefault("tasks_editor_description", "")
    st.session_state.setdefault("tasks_editor_body", "")
    st.session_state.setdefault("tasks_editor_original_name", None)
    st.session_state.setdefault("tasks_run_results", None)

    # Load shared first then user — user-named tasks shadow shared ones.
    for _d in task_storage.visible_task_dirs(current_user_id):
        tasks.load_user_tasks(_d, force_reload=False)
    registered = tasks.all_tasks()

    # --- Counts + clear button (was the sidebar block, now inline) ---------

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

    # --- Existing tasks ----------------------------------------------------

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
                try:
                    parsed = editor.parse_user_task_file(
                        editor.task_file_path(tasks_dir, entry.name)
                    )
                    st.session_state["tasks_editor_open"] = True
                    st.session_state["tasks_editor_name"] = parsed["name"]
                    st.session_state["tasks_editor_description"] = parsed["description"]
                    st.session_state["tasks_editor_body"] = parsed["body"]
                    st.session_state["tasks_editor_original_name"] = parsed["name"]
                    st.rerun()
                except ValueError as exc:
                    st.error(f"Could not open {entry.name}: {exc}")
            if cols[3].button("Delete", key=f"del_{entry.name}"):
                editor.delete_user_task(tasks_dir, entry.name)
                tasks.TASK_REGISTRY.pop(entry.name, None)
                st.rerun()

    # --- New / import controls --------------------------------------------

    col_new, col_import = st.columns(2)
    with col_new:
        if st.button("+ New task", key="tasks_new"):
            st.session_state["tasks_editor_open"] = True
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
            st.session_state["tasks_editor_original_name"] = None
            st.rerun()
    with col_import:
        upl = st.file_uploader(
            "Import a MarcEdit .tasksfile (`.txt`) or `.task` archive",
            type=["txt", "task"],
            accept_multiple_files=False,
            key="tasks_import_uploader",
        )
        if upl is not None and st.button("Import", key="tasks_import_btn"):
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
            else:
                st.rerun()

    # --- Editor ------------------------------------------------------------

    if st.session_state["tasks_editor_open"]:
        st.divider()
        is_edit = st.session_state["tasks_editor_original_name"] is not None
        st.subheader(
            f"Edit `{st.session_state['tasks_editor_original_name']}`"
            if is_edit
            else "New task"
        )

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

        save_col, cancel_col = st.columns([1, 1])
        if save_col.button("Save task", type="primary", key="tasks_save"):
            name = (st.session_state["tasks_editor_name"] or "").strip()
            description = (st.session_state["tasks_editor_description"] or "").strip()
            body = st.session_state["tasks_editor_body"]
            original = st.session_state["tasks_editor_original_name"]
            try:
                editor.save_user_task(
                    tasks_dir,
                    name=name,
                    description=description,
                    body=body,
                    original_name=original,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                if original and original != name:
                    tasks.TASK_REGISTRY.pop(original, None)
                tasks.TASK_REGISTRY.pop(name, None)
                tasks.load_user_tasks(tasks_dir, force_reload=True)
                st.session_state["tasks_editor_open"] = False
                st.success(f"Saved `{name}`.")
                st.rerun()
        if cancel_col.button("Cancel", key="tasks_cancel"):
            st.session_state["tasks_editor_open"] = False
            st.rerun()

    # --- Run on loaded batch ----------------------------------------------

    st.divider()
    st.subheader("Run on loaded batch")

    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on the **Home** page to run tasks "
            "against it. Tasks can be built and imported without a loaded "
            "batch."
        )
    elif not registered:
        st.info("Create or import at least one task above to enable running.")
    else:
        available_names = [t.name for t in registered]
        selection = st.multiselect(
            "Tasks to run (applied in the listed order)",
            options=available_names,
            default=available_names[:1],
            help=(
                "Each task gets a deepcopy of the record; tasks later in the "
                "list see the output of earlier tasks."
            ),
            key="tasks_run_selection",
        )
        if st.button(
            "Run selected tasks",
            type="primary",
            disabled=not selection,
            key="tasks_run_btn",
        ):
            store = session.current_store()
            records = list(store.iter_records()) if store else []
            selected_fns = [tasks.TASK_REGISTRY[n].fn for n in selection]
            out_records: list[pymarc.Record] = []
            issues: list[Issue] = []
            for idx, original in enumerate(records, start=1):
                ident = None
                f001 = original.get("001")
                if f001 is not None and getattr(f001, "data", None):
                    ident = f001.data
                try:
                    working = copy.deepcopy(original)
                    for fn, name in zip(selected_fns, selection):
                        try:
                            fn(working)
                        except Exception as exc:  # noqa: BLE001
                            issues.append(transform_issue(idx, ident, name, exc))
                            break
                    else:
                        out_records.append(working)
                        continue
                    out_records.append(original)
                except Exception as exc:  # noqa: BLE001
                    issues.append(transform_issue(idx, ident, "<deepcopy>", exc))
                    out_records.append(original)

            buf = io.BytesIO()
            writer = pymarc.MARCWriter(buf)
            for rec in out_records:
                writer.write(rec)
            out_bytes = buf.getvalue()

            st.session_state["tasks_run_results"] = {
                "issues": issues,
                "out_bytes": out_bytes,
                "out_filename": _stamped_filename(session.current_filename()),
                "input_count": len(records),
                "output_count": len(out_records),
                "ran_tasks": list(selection),
            }

    results = st.session_state.get("tasks_run_results")
    if results is not None:
        st.divider()
        st.markdown("**Run results**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Records in", results["input_count"])
        c2.metric("Records out", results["output_count"])
        c3.metric("Errors", len(results["issues"]))
        st.caption(
            "Tasks applied: "
            + ", ".join(f"`{n}`" for n in results["ran_tasks"])
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
    """Append a YYYYMMDD-HHMMSS stamp to the filename before its extension."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not orig:
        return f"transformed_{stamp}.mrc"
    p = Path(orig)
    return f"{p.stem}_{stamp}{p.suffix or '.mrc'}"
