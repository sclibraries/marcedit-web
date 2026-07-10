"""Shared record-view modal for virtualized tables (TASK-053).

Three tables (Validate, Report, Find) need a "click to see the
full record" affordance because virtualization truncates the
cells displayed in-grid. Rather than ship three nearly-identical
``@st.dialog`` blocks, this module hosts one configurable opener
the pages call into.

Streamlit's ``st.dataframe(on_select=...)`` is stateful — the
selection persists across reruns until cleared — so each caller
uses a two-step pattern:

1. The cataloger clicks a row in the table; selection state lands
   in ``st.session_state[<table_key>]``.
2. A "View record #N" button appears under the table; clicking it
   calls ``open_record_modal(...)`` which pops the dialog.

This sidesteps the otherwise-unsolvable "dialog keeps reopening
after close" loop you get from auto-opening on selection.
"""

from __future__ import annotations

import html as _html
from typing import Iterable

import streamlit as st

from marcedit_web.lib import mrk_writer
from marcedit_web.lib.record_store import RecordStore


# Severity → background / left-border colors for the highlighted
# MRK line. Tuned so error reads as alarming-but-readable, warning
# matches the page-level yellow circle, info is a soft blue.
_HIGHLIGHT_BG = {
    "error":   "#fde2e2",
    "warning": "#fff3cd",
    "info":    "#d6e9ff",
}
_HIGHLIGHT_BORDER = {
    "error":   "#dc3545",
    "warning": "#cc8800",
    "info":    "#0d6efd",
}


def _render_mrk_highlighted(
    mrk: str, highlight_tag: str, severity: str | None,
) -> None:
    """Render ``mrk`` with the ``=TAG`` line(s) shaded by severity.

    ``st.code`` can't shade individual lines, so we fall back to a
    custom ``<pre>`` block. Match is on the literal ``=TAG`` prefix
    followed by whitespace — pymarc emits e.g. ``=245  10$a...``
    (two spaces between tag and data) for variable fields and
    ``=LDR  ...`` for the leader.
    """
    sev = (severity or "warning").lower()
    bg = _HIGHLIGHT_BG.get(sev, _HIGHLIGHT_BG["warning"])
    border = _HIGHLIGHT_BORDER.get(sev, _HIGHLIGHT_BORDER["warning"])
    parts: list[str] = []
    prefix = f"={highlight_tag}"
    for line in mrk.split("\n"):
        escaped = _html.escape(line) or "&nbsp;"
        is_match = (
            line.startswith(prefix)
            and (len(line) == len(prefix) or line[len(prefix)].isspace())
        )
        if is_match:
            parts.append(
                f'<span style="background:{bg};border-left:3px solid {border};'
                f'padding:1px 6px;display:block;">{escaped}</span>'
            )
        else:
            parts.append(
                f'<span style="padding:1px 6px;display:block;">{escaped}</span>'
            )
    body = "".join(parts)
    st.markdown(
        '<pre style="white-space:pre-wrap;font-family:'
        "'SF Mono',Menlo,Consolas,monospace;background:#f8f9fa;"
        "padding:8px;border-radius:4px;overflow-x:auto;"
        f'font-size:0.85em;line-height:1.35;">{body}</pre>',
        unsafe_allow_html=True,
    )


@st.dialog("Record details", width="large")
def open_record_modal(
    *,
    record_index: int,
    store: RecordStore,
    extra_lines: list[tuple[str, str]] | None = None,
    highlight_tag: str | None = None,
    highlight_severity: str | None = None,
    fix_label: str | None = None,
    on_fix=None,
) -> None:
    """Open a modal showing record ``record_index`` (1-based).

    ``extra_lines`` is rendered above the MRK block as ``**label**:
    body`` pairs. Validate uses this for ``message`` + ``suggestion``;
    Report and Find currently don't pass anything (the record itself
    is the whole story).

    ``highlight_tag`` (e.g. ``"245"`` or ``"LDR"``) shades the
    matching line in the MRK block, themed by ``highlight_severity``
    (``"error"`` / ``"warning"`` / ``"info"``). When omitted the MRK
    renders via the plain ``st.code`` path — Find and Report take
    this default so they aren't affected.

    Raises only via Streamlit's normal dialog teardown when the
    store/record can't be loaded — surfaces a friendly error in
    that case instead of crashing the dialog.
    """
    if store is None:
        st.error("No batch loaded — close this dialog and re-upload.")
        return
    # In-modal spinner so the dialog opens immediately and the
    # cataloger sees progress while pymarc materializes the record.
    # Previously the dialog blocked on this and looked frozen.
    with st.spinner("Loading record…"):
        record = store.get(record_index - 1)
    if record is None:
        st.error(
            f"Record #{record_index} couldn't be loaded — it may be "
            "out of range or malformed."
        )
        return

    identifier = ""
    f001 = record.get("001")
    if f001 is not None:
        identifier = (f001.data or "").strip()
    header = f"Record #{record_index}"
    if identifier:
        header += f" — `{identifier}`"
    st.markdown(f"**{header}**")

    for label, body in extra_lines or []:
        if not body:
            continue
        st.markdown(f"**{label}**")
        # ``st.code`` preserves whitespace and line breaks and is
        # easy to copy. We pick text rendering over markdown so the
        # cataloger sees the literal message text.
        st.code(body, language=None)

    st.markdown("**MARC record (MRK)**")
    mrk = mrk_writer.render_records_mrk([record])
    if highlight_tag:
        _render_mrk_highlighted(mrk, highlight_tag, highlight_severity)
    else:
        st.code(mrk, language=None)

    if fix_label and on_fix is not None:
        if st.button(
            fix_label,
            key=f"_modal_fix_{record_index}_{highlight_tag or 'record'}",
            icon=":material/build:",
            use_container_width=True,
            type="primary",
        ):
            on_fix(record_index, record)
            st.rerun()

    # Handoff to the View page's inline ``.mrk`` editor (TASK-056).
    # Pre-arms the same session-state keys ``render_inline_edit``
    # reads with ``key_prefix="view_edit"`` so the editor lands open
    # with this record's MRK in the buffer; the user goes from
    # "see the issue" to "fix it" in one click. The dialog tears
    # down naturally on ``st.switch_page`` rerun.
    if st.button(
        "✏️ Edit this record",
        key=f"_modal_edit_{record_index}",
        help=(
            "Open this record in the View page's inline .mrk editor. "
            "Saving there commits the edit back into the loaded batch."
        ),
        use_container_width=True,
    ):
        st.session_state["view_index"] = record_index
        st.session_state["view_edit_active"] = True
        st.session_state["view_edit_index"] = record_index
        st.session_state["view_edit_text"] = mrk
        st.switch_page("views/1_View.py")


def selection_view_button(
    *,
    df,
    event,
    record_column: str,
    button_label_template: str,
    button_key: str,
    store: RecordStore,
    extra_lines_from_row=None,
) -> None:
    """Open the record modal on row selection in a virtualized table.

    Call this immediately after the ``st.dataframe(...)`` call:

        event = st.dataframe(df, on_select="rerun", ...)
        selection_view_button(
            df=df, event=event,
            record_column="record",  # column carrying 1-based record #
            button_label_template="View record #{n}",
            button_key="validate_view_btn",
            store=session.current_store(),
            extra_lines_from_row=lambda row: [
                ("Message", row["message"]),
                ("Suggestion", row["suggestion"]),
            ],
        )

    Behavior:

    * Selecting a NEW row in the dataframe auto-opens the modal.
    * After dismissal, the same row stays selected; the user can
      re-open via the explicit "View record" button this helper
      also renders.

    The auto-open + re-open-button pair sidesteps Streamlit's
    persistent-selection quirk (a dialog called every rerun would
    loop). ``last_selected`` tracks the most recently-opened row
    index in session_state so we only auto-open on transitions.

    ``record_column`` values may be strings like ``"3"`` or ``"—"``
    (the latter for issues that don't tie to a specific record); we
    skip the auto-open + button for non-numeric values.
    """
    selected = list(event.selection.rows) if event and getattr(event, "selection", None) else []
    if not selected:
        # Clear the "last opened" marker so the next click on the
        # first row triggers an auto-open. (Selecting nothing = the
        # cataloger explicitly cleared the selection.)
        st.session_state.pop(f"_{button_key}_last_idx", None)
        return
    row = df.iloc[selected[0]]
    raw_idx = str(row[record_column]).strip()
    try:
        record_index = int(raw_idx)
    except ValueError:
        st.caption(
            "Selected row doesn't reference a specific record "
            "(rules-file or batch-scope issue)."
        )
        return
    extras = (
        extra_lines_from_row(row) if extra_lines_from_row else None
    )

    # Auto-open on transitions to a new row. The marker prevents the
    # dialog from reopening on every subsequent rerun while the same
    # row is selected.
    last_key = f"_{button_key}_last_idx"
    if st.session_state.get(last_key) != selected[0]:
        st.session_state[last_key] = selected[0]
        open_record_modal(
            record_index=record_index, store=store, extra_lines=extras,
        )
        return

    # Same row still selected — let the cataloger re-open via the
    # explicit button (closing the modal doesn't drop the selection).
    label = button_label_template.format(n=record_index)
    if st.button(label, key=button_key, icon=":material/visibility:"):
        open_record_modal(
            record_index=record_index, store=store, extra_lines=extras,
        )
