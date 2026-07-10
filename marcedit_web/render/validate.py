"""Validate tab — preflight + rule-driven issue table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from marcedit_web.lib import (
    folio_profiles,
    issue_tags,
    load_readiness,
    preflight,
    rules as rules_mod,
    rules_validate,
    session,
)
from marcedit_web.lib.errors import Issue
from marcedit_web.render._record_modal import open_record_modal


# Visual differentiation for the severity column. We use colored
# circles in front of the label rather than background-color styling
# because Streamlit's selection events ("on_select=rerun") flake out
# when the dataframe is wrapped in a pandas Styler — the Styler
# approach was breaking the "click row → open modal" flow.
# Emoji + text doesn't rely on color alone (a11y).
_SEVERITY_PREFIX = {
    "error": "🔴 error",
    "warning": "🟡 warning",
    "info": "🔵 info",
}


def _decorate_severity(value: str) -> str:
    return _SEVERITY_PREFIX.get(value, value)


# Back-compat alias: ``tests/test_validate_view_button.py`` imports
# this name. The actual logic now lives in ``lib/issue_tags`` so the
# inline editor (TASK-057) can reuse it for Ace annotations.
_tag_for_issue = issue_tags.tag_for_issue


def _folio_context_from_state() -> folio_profiles.FolioContext | None:
    profile_key = str(st.session_state.get("folio_profile_key", "")).strip()
    if not profile_key:
        return None

    return folio_profiles.FolioContext(
        profile_key=profile_key,
        addons=tuple(st.session_state.get("folio_profile_addons") or ()),
        container_code=str(st.session_state.get("folio_container_code", "")).strip(),
        institution_suffix=str(
            st.session_state.get("folio_institution_suffix", "")
        ).strip(),
        collection_name=str(st.session_state.get("folio_collection_name", "")).strip(),
        score_loading=bool(st.session_state.get("folio_score_loading", False)),
        use_949=bool(st.session_state.get("folio_use_949", False)),
        multi_institution=bool(st.session_state.get("folio_multi_institution", False)),
    )


def _compute_issues(
    rule_set: rules_mod.RuleSet | None,
    store,
    malformed: int,
    folio_context: folio_profiles.FolioContext | None = None,
) -> list[Issue]:
    """Run preflight + rules in two streaming passes, wrapped in a
    user-visible status block so the cataloger sees progress."""
    with st.status("Validating records…", expanded=False) as status:
        status.update(label="Preflight pass…")
        preflight_issues = preflight.run_preflight(
            records=store.iter_records() if store else iter([]),
            malformed=malformed,
        )
        status.update(
            label=(
                f"Preflight: {len(preflight_issues)} issue(s). "
                "Applying rules…"
            )
        )
        rule_issues = rules_validate.validate_records(
            store.iter_records() if store else iter([]),
            rule_set,
        )
        status.update(
            label=(
                f"Rules: {len(rule_issues)} issue(s). "
                "Checking load readiness…"
            )
        )
        load_issues = load_readiness.validate_records(
            store.iter_records() if store else iter([]),
        )
        folio_issues: list[Issue] = []
        if folio_context is not None:
            status.update(label="Applying FOLIO profile rules...")
            profile_rules = folio_profiles.rules_for_profile(
                folio_context.profile_key,
                include_addons=folio_context.addons,
            )
            folio_results = folio_profiles.evaluate_records(
                store.iter_records() if store else iter([]),
                profile_rules,
                folio_context,
            )
            folio_issues = [result.issue for result in folio_results]
        all_issues: list[Issue] = (
            preflight_issues + rule_issues + load_issues + folio_issues
        )
        status.update(
            label=f"Done — {len(all_issues)} issue(s) found.",
            state="complete",
        )
    return all_issues


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

    # Memoize the preflight + rules pass across reruns so the View
    # button (and any other widget interaction) doesn't re-trigger
    # the visible "Validating records…" status block. The
    # ``issues_cache`` dict is wiped by ``session.handle_upload`` and
    # by every record-mutating call site (edit / tasks /
    # fixed-field), so the cache stays correct for free.
    cache = st.session_state.setdefault("issues_cache", {})
    folio_context = _folio_context_from_state()
    cache_key = ("validate", folio_context)
    all_issues = cache.get(cache_key)
    if all_issues is None:
        all_issues = _compute_issues(rule_set, store, malformed, folio_context)
        cache[cache_key] = all_issues

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Records", record_count)
    col_b.metric("Errors", sum(1 for i in all_issues if i.severity == "error"))
    col_c.metric("Warnings", sum(1 for i in all_issues if i.severity == "warning"))
    col_d.metric("Info", sum(1 for i in all_issues if i.severity == "info"))

    st.header("Issue table")
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
            # Stash the derived tag on the row so the View widget
            # can pass it to the modal without re-running the
            # regex sweep on every selectbox change.
            "_tag": _tag_for_issue(i) or "",
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

    st.caption(
        f"{len(filtered)} of {len(df)} issues shown. "
        "Pick an issue below and click **View** to see the full record."
    )
    # Display-only dataframe: the explicit View widget below drives
    # modal-opening so we don't take a rerun + re-validation hit on
    # every row click (TASK-055). The ``_tag`` helper column is
    # dropped from the display.
    display = filtered.reset_index(drop=True).copy()
    display["severity"] = display["severity"].map(_decorate_severity)
    st.dataframe(
        display.drop(columns=["_tag"]),
        use_container_width=True,
        hide_index=True,
        key="validate_table",
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

    # View widget: a selectbox of the filtered record-scope issues +
    # a "View" button that opens the modal in a single click. Issues
    # whose ``record`` column isn't a record number (file-scope
    # checks like ``record-count``, ``no-records``) are excluded —
    # they don't map to a viewable record.
    viewable = filtered[filtered["record"].apply(lambda v: str(v).isdigit())]
    if viewable.empty:
        st.caption(
            "No record-scope issues in the filtered set. Adjust the "
            "filters above to view a specific record."
        )
    else:
        view_left, view_right = st.columns([5, 1])
        options = list(viewable.index)

        def _format_choice(idx: int) -> str:
            row = viewable.loc[idx]
            preview = row["message"]
            if len(preview) > 80:
                preview = preview[:77] + "…"
            return (
                f"{row['severity']}  ·  Record #{row['record']}  ·  "
                f"{row['code']}  ·  {preview}"
            )

        with view_left:
            chosen = st.selectbox(
                "Issue to view",
                options=options,
                format_func=_format_choice,
                key="validate_view_select",
                label_visibility="collapsed",
            )
        with view_right:
            clicked = st.button(
                "View",
                key="validate_view_btn",
                icon=":material/visibility:",
                use_container_width=True,
                type="primary",
            )

        if clicked and chosen is not None:
            row = viewable.loc[chosen]
            record_index = int(row["record"])
            tag = row["_tag"] or None
            open_record_modal(
                record_index=record_index,
                store=store,
                extra_lines=[
                    ("Message", row["message"]),
                    ("Suggestion", row.get("suggestion", "")),
                ],
                highlight_tag=tag,
                highlight_severity=row["severity"],
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
