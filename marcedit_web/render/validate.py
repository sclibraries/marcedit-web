"""Validate tab — preflight + rule-driven issue table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from marcedit_web.lib import preflight, rules as rules_mod, rules_validate, session
from marcedit_web.lib.errors import Issue


def render(
    rule_set: rules_mod.RuleSet | None = None,
    rules_warnings: list | None = None,
) -> None:
    """Render the Validate tab into the current Streamlit container."""
    if not session.require_upload("validate records"):
        return

    if rule_set is None or rules_warnings is None:
        from marcedit_web.render import rules_and_warnings_for_page
        rule_set, rules_warnings = rules_and_warnings_for_page()

    store = session.current_store()
    malformed = store.malformed_count() if store else 0
    record_count = store.count() if store else 0

    # Stage 16: stream records through preflight + rules in two separate
    # iterator passes. The RecordStore parses each record on demand and
    # releases it after each pass, so memory stays bounded by O(records ×
    # offsets) instead of O(records × pymarc.Record).
    preflight_issues = preflight.run_preflight(
        records=store.iter_records() if store else iter([]),
        malformed=malformed,
    )
    rule_issues = rules_validate.validate_records(
        store.iter_records() if store else iter([]),
        rule_set,
    )
    all_issues: list[Issue] = preflight_issues + rule_issues

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Records", record_count)
    col_b.metric("Errors", sum(1 for i in all_issues if i.severity == "error"))
    col_c.metric("Warnings", sum(1 for i in all_issues if i.severity == "warning"))
    col_d.metric("Info", sum(1 for i in all_issues if i.severity == "info"))

    st.subheader("Issue table")
    if not all_issues:
        st.success("No issues found.")
        return

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
        key="validate_severity",
    )
    code_options = sorted(df["code"].unique())
    codes = col_f2.multiselect(
        "Code", options=code_options, default=code_options, key="validate_code",
    )
    record_filter = col_f3.text_input(
        "Record # (blank = all)",
        placeholder="e.g. 3",
        key="validate_record_filter",
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
