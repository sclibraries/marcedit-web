"""MarcEditor — MarcEdit-parity in-browser editing of the loaded batch.

The cataloger edits records as MarcEdit-style ``.mrk`` text in a
``streamlit-ace`` block. Apply runs the new text through ``mrk_parser``
+ ``preflight`` + ``rules_validate``; any errors become Ace annotations
(gutter markers + tooltips). Save serializes the resulting records via
``pymarc.MARCWriter`` and offers a download; the session's
``records`` list is also updated so other pages see the edited batch.

Hard cap: batches larger than ``MAX_EDITOR_RECORDS`` render read-only
with a banner. The user is directed to the Tasks page for large-batch
transforms.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    mrk_parser,
    mrk_writer,
    preflight,
    rules,
    rules_validate,
    session,
)
from marcedit_web.lib.errors import Issue

logger = logging.getLogger("marcedit_web.marc_editor")

MAX_EDITOR_RECORDS = 5000


def _is_fatal_code(code: str) -> bool:
    """LineError codes that block Save.

    Most parse errors are non-fatal — the parser keeps going. Only the
    truly structural codes (missing leader, leader length, bad-line)
    should stop the cataloger from saving the batch back.
    """
    return code in {"missing-leader", "ldr-length", "bad-line", "encoding"}

st.set_page_config(page_title="MarcEditor · marcedit-web", layout="wide")
session.init()

st.title("MarcEditor")
st.caption(
    "Edit the loaded batch as MarcEdit-style `.mrk` text. Apply runs the parser "
    "and validators; Save serializes back to `.mrc` and updates this session's "
    "records so View / Validate / Report / Diff see the edits."
)


# --- Sidebar status --------------------------------------------------------


with st.sidebar:
    st.header("marcedit-web")
    user = st.session_state.get("user", "anonymous")
    st.caption(f"Signed in as **{user}**")
    st.divider()
    if session.has_upload():
        st.caption(f"Loaded: `{session.current_filename() or '(unnamed)'}`")
        st.caption(f"{len(session.current_records())} records")
    else:
        st.caption("No file loaded yet.")


# --- Empty state -----------------------------------------------------------


if not session.has_upload():
    st.info(
        "Upload a `.mrc` file from the **Home** page first. The MarcEditor "
        "edits records already in this session."
    )
    st.stop()

records = session.current_records()
total = len(records)
if total == 0:
    st.warning("The loaded file produced no parseable records.")
    st.stop()


# --- Cap on batch size -----------------------------------------------------


over_cap = total > MAX_EDITOR_RECORDS
if over_cap:
    st.warning(
        f"This batch contains **{total}** records, above the editor's "
        f"`{MAX_EDITOR_RECORDS}`-record cap. The text below is read-only "
        "so parse-on-Apply doesn't stall the page. Use the **Tasks** page "
        "to apply transforms to the full batch, then come back here to "
        "review a subset."
    )


# --- Editor state ----------------------------------------------------------


# Cache the initial .mrk text in session_state so flipping between pages
# doesn't re-render thousands of records every visit. The cache is keyed
# on STABLE identifiers (filename + record count); `id()` of the records
# list isn't stable across reruns because `session.current_records()`
# returns a fresh list copy each call.
_MRK_KEY = "marc_editor_text"
_MRK_SOURCE_KEY = "marc_editor_source_id"
source_id = (session.current_filename(), total)

if (
    _MRK_KEY not in st.session_state
    or st.session_state.get(_MRK_SOURCE_KEY) != source_id
):
    st.session_state[_MRK_KEY] = mrk_writer.render_records_mrk(records)
    st.session_state[_MRK_SOURCE_KEY] = source_id
    # Reset derived state — the cache identity changed.
    st.session_state.pop("marc_editor_parse", None)


# --- Rules (cached) -------------------------------------------------------


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marc-rules.txt"


@st.cache_data(show_spinner=False)
def _load_rules(path_str: str, mtime: float):
    return rules.parse_rules(Path(path_str))


def _rules_for_page() -> rules.RuleSet:
    if not _RULES_PATH.exists():
        return rules.RuleSet()
    rule_set, _ = _load_rules(str(_RULES_PATH), _RULES_PATH.stat().st_mtime)
    return rule_set


rule_set = _rules_for_page()


# --- Toolbar --------------------------------------------------------------


col_a, col_b, col_c = st.columns([1, 1, 4])
reload_clicked = col_a.button(
    "Reload from records",
    help=(
        "Re-render the editor text from `st.session_state.records`. "
        "Discards any unapplied edits in the editor."
    ),
)
if reload_clicked:
    st.session_state[_MRK_KEY] = mrk_writer.render_records_mrk(records)
    st.session_state.pop("marc_editor_parse", None)
    st.rerun()


# --- Ace editor -----------------------------------------------------------


# Build Ace annotations from the most-recent parse, if any.
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
            row = max(
                0,
                parse_state["record_start_lines"][idx - 1] - 1,
            ) if idx <= len(parse_state["record_start_lines"]) else 0
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

# `st_ace` returns the current text on every rerun when auto_update=False
# (the value is committed when the user presses Apply / Cmd+Enter inside
# the editor). We mirror the committed value into our own session key so
# Parse + validate can pick it up. We deliberately do NOT pop the parse
# state here — streamlit-ace can return semantically-equivalent text with
# tiny whitespace differences that would wipe the parse on every rerun.
# Parse + validate is the explicit "freshen" action.
if new_text is not None:
    st.session_state[_MRK_KEY] = new_text


# --- Parse + validate (button-triggered) ----------------------------------


col_p, col_s, col_status = st.columns([1, 1, 4])
parse_clicked = col_p.button(
    "Parse + validate",
    disabled=over_cap,
    type="secondary",
    help=(
        "Re-parse the current editor text and run preflight + rules "
        "validation. Errors surface as Ace annotations."
    ),
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

    # Run preflight + rule validation against the freshly parsed records.
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


# --- Save button + status ------------------------------------------------


parse_state = st.session_state.get("marc_editor_parse")
fatal = parse_state["fatal_count"] if parse_state else 0
save_clicked = col_s.button(
    "Save to records + download",
    disabled=over_cap or parse_state is None or fatal > 0,
    type="primary",
    help=(
        "Push the parsed records back into `st.session_state.records` "
        "(so other pages see the edits) and offer the resulting `.mrc` "
        "as a download. Disabled until Parse runs cleanly."
    ),
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


# --- Save flow -----------------------------------------------------------


if save_clicked and parse_state is not None and fatal == 0:
    record_objs = parse_state["records"]
    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for r in record_objs:
        writer.write(r)
    out_bytes = buf.getvalue()

    # Push the edited records back into the shared session.
    st.session_state["records"] = list(record_objs)
    st.session_state["raw_bytes"] = out_bytes
    st.session_state["malformed_count"] = 0
    st.session_state["issues_cache"] = {}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    orig = session.current_filename() or "edited.mrc"
    stem = Path(orig).stem or "edited"
    fname = f"{stem}_{stamp}.mrc"

    st.success(
        f"Saved **{len(record_objs)}** record(s) back into the session. "
        f"Download below or open another page to see the edits."
    )
    st.download_button(
        label=f"Download {fname}",
        data=out_bytes,
        file_name=fname,
        mime="application/marc",
        key="marc_editor_download",
    )


# --- Issue tables --------------------------------------------------------


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
                        "record": i["record_index"] or "—",
                        "message": i["message"],
                    }
                    for i in parse_state["issues"]
                ],
                hide_index=True,
                use_container_width=True,
            )
