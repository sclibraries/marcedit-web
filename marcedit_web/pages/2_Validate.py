"""Validate — surfaces preflight + rule-driven issues for the loaded batch.

Reads records from `st.session_state.records` and emits a filterable
issue table that combines:

* `preflight.run_preflight` — structural sanity (missing 001/245/856,
  empty 856 $u, leader length, duplicate 001/OCLC/LCCN, malformed-
  record counts).
* `rules_validate.validate_records` — rule-driven checks against
  `data/marc-rules.txt` (tag repeatability, indicator validity,
  subfield validity, length, only-one-1xx, missing-245).

Rule parsing is cached for the life of the Streamlit server process so
flipping between pages stays snappy even after we ship a larger rules
file. The records list is held in `st.session_state` so revisiting the
page rerenders the same data without re-uploading.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from marcedit_web.lib import preflight, rules, rules_validate, session
from marcedit_web.lib.errors import Issue

st.set_page_config(page_title="Validate · marcedit-web", layout="wide")
session.init()

st.title("Validate")
st.caption("Structural preflight + rules from `data/marc-rules.txt`.")


# --- Sidebar status --------------------------------------------------------


with st.sidebar:
    st.header("marcedit-web")
    user = st.session_state.get("user", "anonymous")
    st.caption(f"Signed in as **{user}**")
    st.divider()
    if session.has_upload():
        st.caption(f"Loaded: `{session.current_filename() or '(unnamed)'}`")
        st.caption(f"{session.record_count()} records")
    else:
        st.caption("No file loaded yet.")


# --- Empty state -----------------------------------------------------------


if not session.has_upload():
    st.info(
        "Upload a `.mrc` file from the **Home** page first. Validate runs "
        "against records already in this session."
    )
    st.stop()


# --- Rules parsing (cached) ------------------------------------------------


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marc-rules.txt"


@st.cache_data(show_spinner=False)
def _load_rules(path_str: str, mtime: float):
    """Parse the rules file. `mtime` busts the cache on edit."""
    return rules.parse_rules(Path(path_str))


def _parse_rules_for_page():
    if not _RULES_PATH.exists():
        return rules.RuleSet(), []
    return _load_rules(str(_RULES_PATH), _RULES_PATH.stat().st_mtime)


rule_set, rules_warnings = _parse_rules_for_page()


# --- Run validations -------------------------------------------------------


store = session.current_store()
records = list(store.iter_records()) if store else []
malformed = store.malformed_count() if store else 0

preflight_issues = preflight.run_preflight(
    records=records, malformed=malformed,
)
rule_issues = rules_validate.validate_records(records, rule_set)
all_issues: list[Issue] = preflight_issues + rule_issues


# --- Top-level summary ------------------------------------------------------


col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Records", len(records))
col_b.metric(
    "Errors",
    sum(1 for i in all_issues if i.severity == "error"),
)
col_c.metric(
    "Warnings",
    sum(1 for i in all_issues if i.severity == "warning"),
)
col_d.metric(
    "Info",
    sum(1 for i in all_issues if i.severity == "info"),
)


# --- Filters ---------------------------------------------------------------


st.subheader("Issue table")

if not all_issues:
    st.success("No issues found.")
    st.stop()

issue_rows = [
    {
        "severity": i.severity,
        "scope": i.scope,
        "code": i.code,
        "record": str(i.record_index) if i.record_index else "—",
        "identifier": i.identifier or "—",
        "message": i.message,
        "suggestion": i.suggestion or "",
    }
    for i in all_issues
]
df = pd.DataFrame(issue_rows)

col_f1, col_f2, col_f3 = st.columns(3)
sev_options = sorted(df["severity"].unique())
severities = col_f1.multiselect(
    "Severity",
    options=sev_options,
    default=[s for s in sev_options if s != "info"] or sev_options,
)
code_options = sorted(df["code"].unique())
codes = col_f2.multiselect("Code", options=code_options, default=code_options)
record_filter = col_f3.text_input(
    "Record # (blank = all)",
    placeholder="e.g. 3",
)

filtered = df
if severities:
    filtered = filtered[filtered["severity"].isin(severities)]
if codes:
    filtered = filtered[filtered["code"].isin(codes)]
if record_filter.strip():
    needle = record_filter.strip()
    try:
        int(needle)
        filtered = filtered[filtered["record"] == needle]
    except ValueError:
        st.warning(f"Ignoring non-numeric record filter {needle!r}.")

st.caption(f"{len(filtered)} of {len(df)} issues shown.")
st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
    column_config={
        "severity": st.column_config.TextColumn("Severity", width="small"),
        "scope": st.column_config.TextColumn("Scope", width="small"),
        "code": st.column_config.TextColumn("Code", width="medium"),
        "record": st.column_config.TextColumn("Record #", width="small"),
        "identifier": st.column_config.TextColumn("Identifier", width="medium"),
        "message": st.column_config.TextColumn("Message", width="large"),
        "suggestion": st.column_config.TextColumn("Suggestion", width="large"),
    },
)


# --- Rules-file warnings (the parse phase, not the records) ----------------


if rules_warnings:
    with st.expander(
        f"Rules-file warnings ({len(rules_warnings)})",
        expanded=False,
    ):
        st.caption(
            "These are non-fatal issues the parser found in "
            "`data/marc-rules.txt` itself."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "line": w.line_no,
                        "content": w.line,
                        "warning": w.message,
                    }
                    for w in rules_warnings
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
