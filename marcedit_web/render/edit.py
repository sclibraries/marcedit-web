"""Edit tab — streamlit-ace `.mrk` editor with parse-on-Apply + Save."""

from __future__ import annotations

import logging
from pathlib import Path

import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib.audit import audit_event
from marcedit_web.lib import (
    mrk_parser,
    mrk_writer,
    preflight,
    rules as rules_mod,
    rules_validate,
    session,
    snapshot_actions,
    viewer,
)
from marcedit_web.render import fixed_field_helper, single_record_edit

logger = logging.getLogger("marcedit_web.render.edit")

MAX_EDITOR_RECORDS = 5000
RECORD_MODE = "Record editor"
SOURCE_MODE = "Advanced full-batch .mrk source"


def _is_fatal_code(code: str) -> bool:
    """LineError codes that block Save."""
    return code in {"missing-leader", "ldr-length", "bad-line", "encoding"}


_K_PICK_INDEX = "edit_pick_index"
_K_EDITOR_MODE = "marc_editor_mode"


def _editor_mode_options(total: int) -> list[str]:
    """Return available MarcEditor modes for the loaded record count."""
    if total > MAX_EDITOR_RECORDS:
        return [RECORD_MODE]
    return [RECORD_MODE, SOURCE_MODE]


def _default_editor_mode(total: int) -> str:
    """Default MarcEditor to the cataloger-friendly one-record editor."""
    return _editor_mode_options(total)[0]


def _render_single_record_picker(store, total: int, rule_set) -> None:
    """Render a record-number picker + per-record inline editor.

    The over-cap fallback for the Edit tab: instead of going read-only,
    let the cataloger jump to any record by number and edit just that
    one. Same shared inline-edit helper the View page uses, namespaced
    under ``workspace_edit_*`` keys so it doesn't collide with View's
    ``view_edit_*`` state.
    """
    st.session_state.setdefault(_K_PICK_INDEX, 1)

    nav_a, nav_b, nav_c, _ = st.columns([1, 3, 1, 1])

    def _step(delta: int) -> None:
        cur = int(st.session_state.get(_K_PICK_INDEX, 1))
        nxt = max(1, min(total, cur + delta))
        st.session_state[_K_PICK_INDEX] = nxt

    nav_a.button(
        "◀ Prev",
        on_click=_step,
        args=(-1,),
        disabled=int(st.session_state[_K_PICK_INDEX]) <= 1,
        use_container_width=True,
        key="edit_pick_prev",
    )
    nav_b.number_input(
        "Record #",
        min_value=1,
        max_value=total,
        step=1,
        key=_K_PICK_INDEX,
        label_visibility="collapsed",
    )
    nav_c.button(
        "Next ▶",
        on_click=_step,
        args=(1,),
        disabled=int(st.session_state[_K_PICK_INDEX]) >= total,
        use_container_width=True,
        key="edit_pick_next",
    )

    index = int(st.session_state[_K_PICK_INDEX])
    record = store.get(index - 1)
    if record is None:
        st.warning(f"Record {index} not found.")
        return

    identifier = viewer.record_identifier(record)
    title = viewer.record_title(record) or "(no 245 $a)"
    st.markdown(
        f"**Record {index:,} of {total:,}** — `{identifier}` — {title}"
    )

    single_record_edit.render_inline_edit(
        store=store,
        index=index,
        record=record,
        rule_set=rule_set,
        key_prefix="workspace_edit",
        start_open=True,
    )

    with st.expander("Record source preview", expanded=False):
        st.code(viewer.render_record_human(record), language="text")

    fixed_field_helper.render_fixed_field_helper(
        store=store,
        index=index,
        record=record,
        key_prefix="workspace_control",
    )

    fixed_field_helper.render_008_helper(
        store=store,
        index=index,
        record=record,
        key_prefix="workspace_008",
    )


def render(rule_set: rules_mod.RuleSet | None = None) -> None:
    """Render the MarcEditor tab into the current Streamlit container."""
    if not session.require_upload("edit records in MarcEditor"):
        return

    store = session.current_store()
    total = store.count() if store else 0
    if total == 0:
        st.warning("The loaded file produced no parseable records.")
        return

    if rule_set is None:
        from marcedit_web.render import rules_for_page
        rule_set = rules_for_page()

    over_cap = total > MAX_EDITOR_RECORDS
    mode_options = _editor_mode_options(total)
    current_mode = st.session_state.get(_K_EDITOR_MODE)
    if current_mode not in mode_options:
        st.session_state[_K_EDITOR_MODE] = _default_editor_mode(total)

    if len(mode_options) > 1:
        st.radio(
            "MarcEditor mode",
            mode_options,
            horizontal=True,
            key=_K_EDITOR_MODE,
        )
    else:
        st.session_state[_K_EDITOR_MODE] = RECORD_MODE

    if st.session_state[_K_EDITOR_MODE] == RECORD_MODE:
        if over_cap:
            st.info(
                f"This batch contains **{total:,}** records, above the "
                f"`{MAX_EDITOR_RECORDS:,}`-record cap for the full-batch "
                "text editor. **Per-record editing is enabled below** — "
                "pick a record by number to edit it. For bulk transforms "
                "across all records, use the **Tasks** page."
            )
        _render_single_record_picker(store, total, rule_set)
        return

    _MRK_KEY = "marc_editor_text"
    _MRK_SOURCE_KEY = "marc_editor_source_id"
    source_id = (session.current_filename(), total)

    if (
        _MRK_KEY not in st.session_state
        or st.session_state.get(_MRK_SOURCE_KEY) != source_id
    ):
        if over_cap:
            st.session_state[_MRK_KEY] = ""
        else:
            st.session_state[_MRK_KEY] = mrk_writer.render_records_mrk(
                store.iter_records()
            )
        st.session_state[_MRK_SOURCE_KEY] = source_id
        st.session_state.pop("marc_editor_parse", None)

    # --- Toolbar ------------------------------------------------------------

    col_a, _col_b, _col_c = st.columns([1, 1, 4])
    reload_clicked = col_a.button(
        "Reload from records",
        disabled=over_cap,
        help=(
            "Re-render the editor text from the loaded batch. "
            "Discards any unapplied edits in the editor."
        ),
        key="marc_editor_reload",
    )
    if reload_clicked:
        st.session_state[_MRK_KEY] = mrk_writer.render_records_mrk(
            store.iter_records()
        )
        st.session_state.pop("marc_editor_parse", None)
        st.rerun()

    # --- Ace annotations ---------------------------------------------------

    annotations: list[dict] = []
    parse_state = st.session_state.get("marc_editor_parse")
    if parse_state is not None:
        for err in parse_state["line_errors"]:
            annotations.append({
                "row": max(0, err["line_no"] - 1),
                "column": max(0, err["column"]),
                "type": "error",
                "text": f"{err['code']}: {err['message']}",
            })
        for iss in parse_state["issues"]:
            if iss.get("record_index") and parse_state["record_start_lines"]:
                idx = iss["record_index"]
                row = (
                    max(0, parse_state["record_start_lines"][idx - 1] - 1)
                    if idx <= len(parse_state["record_start_lines"])
                    else 0
                )
            else:
                row = 0
            type_ = (
                "error" if iss["severity"] == "error"
                else "warning" if iss["severity"] == "warning"
                else "info"
            )
            annotations.append({
                "row": row,
                "column": 0,
                "type": type_,
                "text": f"[{iss['severity']}] {iss['code']}: {iss['message']}",
            })

    new_text = st_ace(
        value=st.session_state[_MRK_KEY],
        language="text",
        theme="github",
        keybinding="vscode",
        font_size=12,
        tab_size=2,
        wrap=False,
        show_gutter=True,
        show_print_margin=False,
        auto_update=False,
        annotations=annotations,
        readonly=over_cap,
        min_lines=24,
        height=500,
        key="marc_editor_ace",
    )

    if new_text is not None:
        st.session_state[_MRK_KEY] = new_text

    # --- Parse + Save ------------------------------------------------------

    col_p, col_s, col_status = st.columns([1, 1, 4])
    parse_clicked = col_p.button(
        "Parse + validate",
        disabled=over_cap,
        type="secondary",
        help=(
            "Re-parse the current editor text and run preflight + rules "
            "validation. Errors surface as Ace annotations."
        ),
        key="marc_editor_parse_btn",
    )

    if parse_clicked:
        text = st.session_state[_MRK_KEY]
        parsed_records, file_errors = mrk_parser.parse_mrk(text)

        record_objs: list[pymarc.Record] = []
        record_start_lines: list[int] = []
        line_errors_serialized: list[dict] = []

        for fe in file_errors:
            line_errors_serialized.append({
                "line_no": fe.line_no,
                "column": fe.column,
                "code": fe.code,
                "message": fe.message,
            })
        for pr in parsed_records:
            record_start_lines.append(pr.start_line)
            if pr.record is not None:
                record_objs.append(pr.record)
            for e in pr.errors:
                line_errors_serialized.append({
                    "line_no": e.line_no,
                    "column": e.column,
                    "code": e.code,
                    "message": e.message,
                })

        preflight_issues = preflight.run_preflight(records=record_objs, malformed=0)
        rule_issues = rules_validate.validate_records(record_objs, rule_set)
        all_issues = preflight_issues + rule_issues
        serialized_issues = [
            {
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "record_index": i.record_index,
            }
            for i in all_issues
        ]

        fatal_count = sum(
            1 for e in line_errors_serialized if _is_fatal_code(e["code"])
        ) + sum(1 for i in all_issues if i.severity == "error")

        st.session_state["marc_editor_parse"] = {
            "line_errors": line_errors_serialized,
            "issues": serialized_issues,
            "record_count": len(record_objs),
            "record_start_lines": record_start_lines,
            "fatal_count": fatal_count,
            "records": record_objs,
        }
        st.rerun()

    parse_state = st.session_state.get("marc_editor_parse")
    fatal = parse_state["fatal_count"] if parse_state else 0
    save_clicked = col_s.button(
        "Save to records + download",
        disabled=over_cap or parse_state is None or fatal > 0,
        type="primary",
        help=(
            "Push the parsed records back into the session's RecordStore "
            "(so other pages see the edits) and offer the resulting `.mrc` "
            "as a download. Disabled until Parse runs cleanly."
        ),
        key="marc_editor_save_btn",
    )

    if parse_state is None:
        col_status.caption(
            "Click **Parse + validate** to check the current text. "
            "Save unlocks when there are no fatal errors."
        )
    else:
        parse_count = parse_state["record_count"]
        warnings = sum(
            1 for i in parse_state["issues"] if i["severity"] == "warning"
        )
        info = sum(1 for i in parse_state["issues"] if i["severity"] == "info")
        col_status.caption(
            f"Parsed **{parse_count}** record(s); "
            f"**{fatal}** fatal, **{warnings}** warning, **{info}** info."
        )

    if save_clicked and parse_state is not None and fatal == 0:
        record_objs = parse_state["records"]
        with snapshot_actions.staged_store_path(store) as before_path:
            store.replace_all(list(record_objs))
            try:
                store.persist_to_disk()
            except OSError as exc:
                st.error(f"Cannot save: edited records were not persisted. {exc}")
                return

            snapshot = snapshot_actions.record_job_snapshot(
                job_id=st.session_state.get("current_job_id"),
                user_email=session.current_user_id(),
                kind="edit",
                label="Full MARC editor save",
                before_path=before_path,
                after_path=store.path,
                summary={
                    "record_count": len(record_objs),
                    "source": "marc-editor",
                },
            )
        if snapshot is not None:
            audit_event(
                "job-snapshot-created",
                user=session.current_user_id(),
                snapshot_id=snapshot["id"],
                job_id=snapshot["job_id"],
                kind=snapshot["kind"],
            )
        st.session_state["issues_cache"] = {}

        orig = session.current_filename() or "edited.mrc"
        stem = Path(orig).stem or "edited"
        fname = session.stamped_filename(stem)

        st.success(
            f"Saved **{len(record_objs)}** record(s) back into the session. "
            f"Download below or open another page to see the edits."
        )
        st.download_button(
            label=f"Download {fname}",
            data=store.path.read_bytes(),
            file_name=fname,
            mime="application/marc",
            key="marc_editor_download",
        )

    # --- Issue tables -----------------------------------------------------

    if parse_state is not None and (parse_state["line_errors"] or parse_state["issues"]):
        st.divider()
        with st.expander(
            f"Errors and warnings "
            f"({len(parse_state['line_errors'])} line-pinned, "
            f"{len(parse_state['issues'])} rule/preflight)",
            expanded=fatal > 0,
        ):
            if parse_state["line_errors"]:
                st.markdown("**Line-pinned parse errors**")
                st.dataframe(
                    [
                        {
                            "line": e["line_no"],
                            "col": e["column"],
                            "code": e["code"],
                            "message": e["message"],
                        }
                        for e in parse_state["line_errors"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            if parse_state["issues"]:
                st.markdown("**Preflight + rule validation**")
                st.dataframe(
                    [
                        {
                            "severity": i["severity"],
                            "code": i["code"],
                            "record": str(i["record_index"]) if i["record_index"] else "—",
                            "message": i["message"],
                        }
                        for i in parse_state["issues"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
