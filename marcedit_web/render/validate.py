"""Validate tab — preflight + rule-driven issue table."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class _ValidationResult:
    issues: list[Issue]
    fixable_issue_keys: set[tuple[str, int | None]]


@dataclass(frozen=True)
class _FolioPreviewState:
    preview: folio_profiles.FolioBatchPreview
    store_revision: int
    folio_context: folio_profiles.FolioContext
    rule_keys: tuple[str, ...]


def _build_folio_context(
    *,
    profile_key: str,
    addon_enabled: bool,
    institution_suffix: str,
    container_code: str,
    collection_name: str = "",
    multi_institution: bool = False,
    score_loading: bool = False,
) -> folio_profiles.FolioContext | None:
    if not profile_key:
        return None
    addons = ("folio-ecollection-ebook",) if addon_enabled else ()
    return folio_profiles.FolioContext(
        profile_key=profile_key,
        addons=addons,
        container_code=container_code.strip(),
        institution_suffix=institution_suffix.strip().upper(),
        collection_name=collection_name.strip(),
        multi_institution=multi_institution,
        score_loading=score_loading,
    )


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
    return _compute_validation_result(
        rule_set,
        store,
        malformed,
        folio_context,
    ).issues


def _compute_validation_result(
    rule_set: rules_mod.RuleSet | None,
    store,
    malformed: int,
    folio_context: folio_profiles.FolioContext | None = None,
) -> _ValidationResult:
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
        fixable_issue_keys: set[tuple[str, int | None]] = set()
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
            fixable_issue_keys = {
                (result.issue.code, result.issue.record_index)
                for result in folio_results
                if result.fix_available
            }
        all_issues: list[Issue] = (
            preflight_issues + rule_issues + load_issues + folio_issues
        )
        status.update(
            label=f"Done — {len(all_issues)} issue(s) found.",
            state="complete",
        )
    return _ValidationResult(all_issues, fixable_issue_keys)


def _build_issue_rows(
    issues: list[Issue],
    fixable_issue_keys: set[tuple[str, int | None]],
) -> list[dict[str, str]]:
    return [
        {
            "severity": issue.severity,
            "scope": issue.scope,
            "code": issue.code,
            "record": str(issue.record_index) if issue.record_index else "—",
            "identifier": issue.identifier or "—",
            "message": issue.message,
            "suggestion": issue.suggestion or "",
            "fix_available": (
                "yes"
                if (issue.code, issue.record_index) in fixable_issue_keys
                else ""
            ),
            # Stash the derived tag on the row so the View widget
            # can pass it to the modal without re-running the
            # regex sweep on every selectbox change.
            "_tag": _tag_for_issue(issue) or "",
        }
        for issue in issues
    ]


def _preview_to_rows(
    preview: folio_profiles.FolioBatchPreview,
) -> list[dict[str, object]]:
    records = _format_record_numbers(preview.affected_record_numbers)
    return [
        {"rule": rule, "fixes": count, "records": records}
        for rule, count in sorted(preview.by_rule.items())
    ]


def _format_record_numbers(record_numbers: list[int]) -> str:
    return ", ".join(str(number) for number in sorted(record_numbers))


def _rule_keys(rules: list[folio_profiles.FolioRule]) -> tuple[str, ...]:
    return tuple(sorted(rule.key for rule in rules))


def _build_folio_preview_state(
    *,
    preview: folio_profiles.FolioBatchPreview,
    store_revision: int,
    folio_context: folio_profiles.FolioContext,
    profile_rules: list[folio_profiles.FolioRule],
) -> _FolioPreviewState:
    return _FolioPreviewState(
        preview=preview,
        store_revision=store_revision,
        folio_context=folio_context,
        rule_keys=_rule_keys(profile_rules),
    )


def _folio_preview_state_is_current(
    state: _FolioPreviewState,
    *,
    store_revision: int,
    folio_context: folio_profiles.FolioContext,
    profile_rules: list[folio_profiles.FolioRule],
) -> bool:
    return (
        state.store_revision == store_revision
        and state.folio_context == folio_context
        and state.rule_keys == _rule_keys(profile_rules)
    )


def _find_single_folio_fix_rule(
    record,
    issue_code: str,
    rules: list[folio_profiles.FolioRule],
    context: folio_profiles.FolioContext,
) -> folio_profiles.FolioRule | None:
    matches = []
    for item in folio_profiles.evaluate_record(record, rules, context):
        if item.issue.code == issue_code and item.fix_available:
            matches.append(next(rule for rule in rules if rule.key == item.rule_key))
    return matches[0] if len(matches) == 1 else None


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

    st.subheader("FOLIO profile")
    profiles = [
        profile for profile in folio_profiles.list_profiles() if not profile.is_addon
    ]
    profile_options = [""] + [profile.key for profile in profiles]
    profile_labels = {"": "No FOLIO profile"}
    profile_labels.update({profile.key: profile.label for profile in profiles})
    selected_profile = st.selectbox(
        "Profile",
        options=profile_options,
        format_func=lambda key: profile_labels.get(key, key),
        key="folio_profile_key",
    )
    addon_enabled = st.checkbox(
        "Apply e-collection ebook rules",
        value=False,
        key="folio_ebook_addon",
    )
    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
    container_code = col_cfg1.text_input(
        "Container code",
        key="folio_container_code",
    )
    institution_suffix = col_cfg2.text_input(
        "Institution suffix",
        placeholder="SC",
        key="folio_institution_suffix",
    )
    score_loading = col_cfg3.checkbox(
        "Score loading",
        value=False,
        key="folio_score_loading",
    )
    collection_name = st.text_input(
        "Collection name",
        key="folio_collection_name",
    )
    multi_institution = st.checkbox(
        "Multi-institution load",
        value=False,
        key="folio_multi_institution",
    )
    folio_context = _build_folio_context(
        profile_key=selected_profile,
        addon_enabled=addon_enabled,
        institution_suffix=institution_suffix,
        container_code=container_code,
        collection_name=collection_name,
        multi_institution=multi_institution,
        score_loading=score_loading,
    )

    # Memoize the preflight + rules pass across reruns so the View
    # button (and any other widget interaction) doesn't re-trigger
    # the visible "Validating records…" status block. The
    # ``issues_cache`` dict is wiped by ``session.handle_upload`` and
    # by every record-mutating call site (edit / tasks /
    # fixed-field), so the cache stays correct for free.
    cache = st.session_state.setdefault("issues_cache", {})
    cache_key = (
        "validate",
        store.revision if store else 0,
        folio_context,
    )
    validation_result = cache.get(cache_key)
    if validation_result is None:
        validation_result = _compute_validation_result(
            rule_set,
            store,
            malformed,
            folio_context,
        )
        cache.clear()
        cache[cache_key] = validation_result
    all_issues = validation_result.issues

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Records", record_count)
    col_b.metric("Errors", sum(1 for i in all_issues if i.severity == "error"))
    col_c.metric("Warnings", sum(1 for i in all_issues if i.severity == "warning"))
    col_d.metric("Info", sum(1 for i in all_issues if i.severity == "info"))

    st.header("Issue table")
    if not all_issues:
        st.success("No issues found.")
        return

    issue_rows = _build_issue_rows(
        all_issues,
        validation_result.fixable_issue_keys,
    )
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
            "fix_available": st.column_config.TextColumn("Fix", width="small"),
        },
    )

    if folio_context is not None and store is not None:
        profile_rules = folio_profiles.rules_for_profile(
            folio_context.profile_key,
            include_addons=folio_context.addons,
        )
        if st.button(
            "Preview FOLIO safe fixes",
            key="folio_preview_safe_fixes",
            icon=":material/rule_settings:",
        ):
            st.session_state["folio_safe_fix_preview"] = _build_folio_preview_state(
                preview=folio_profiles.preview_batch_fixes(
                    store.iter_records(),
                    profile_rules,
                    folio_context,
                ),
                store_revision=store.revision,
                folio_context=folio_context,
                profile_rules=profile_rules,
            )
            st.rerun()
        preview_state = st.session_state.get("folio_safe_fix_preview")
        if preview_state is not None and not isinstance(
            preview_state,
            _FolioPreviewState,
        ):
            preview_state = None
            st.session_state.pop("folio_safe_fix_preview", None)
        if preview_state is not None and not _folio_preview_state_is_current(
            preview_state,
            store_revision=store.revision,
            folio_context=folio_context,
            profile_rules=profile_rules,
        ):
            preview_state = None
            st.session_state.pop("folio_safe_fix_preview", None)
            st.warning(
                "FOLIO safe-fix preview is stale. Preview again before applying."
            )
        if preview_state is not None:
            preview = preview_state.preview
            st.subheader("FOLIO safe-fix preview")
            st.caption(
                f"{preview.total_fixes} fix(es) across "
                f"{preview.affected_records} record(s)."
            )
            st.dataframe(
                pd.DataFrame(_preview_to_rows(preview)),
                hide_index=True,
                use_container_width=True,
            )
            if preview.samples:
                with st.expander("Preview samples", expanded=False):
                    for sample in preview.samples:
                        st.markdown(
                            f"**Record #{sample.record_index}: {sample.label}**"
                        )
                        st.code(sample.before, language=None)
                        st.code(sample.after, language=None)
            if st.button(
                "Apply previewed FOLIO fixes",
                key="folio_apply_safe_fixes",
                type="primary",
                icon=":material/check:",
            ):
                if not _folio_preview_state_is_current(
                    preview_state,
                    store_revision=store.revision,
                    folio_context=folio_context,
                    profile_rules=profile_rules,
                ):
                    st.session_state.pop("folio_safe_fix_preview", None)
                    st.warning(
                        "FOLIO safe-fix preview is stale. "
                        "Preview again before applying."
                    )
                    st.rerun()
                else:
                    folio_profiles.apply_batch_fixes_to_store(
                        store,
                        profile_rules,
                        folio_context,
                    )
                    st.session_state.pop("folio_safe_fix_preview", None)
                    st.session_state.pop("issues_cache", None)
                    st.success("FOLIO safe fixes applied.")
                    st.rerun()

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
            fix_label = None
            on_fix = None
            if folio_context is not None and row["code"].startswith("folio-"):
                profile_rules = folio_profiles.rules_for_profile(
                    folio_context.profile_key,
                    include_addons=folio_context.addons,
                )
                current_record = store.get(record_index - 1)
                fix_rule = (
                    _find_single_folio_fix_rule(
                        current_record,
                        row["code"],
                        profile_rules,
                        folio_context,
                    )
                    if current_record is not None
                    else None
                )
                if fix_rule is not None:
                    fix_label = "Apply FOLIO safe fix"

                    def on_fix(record_no: int, record, *, _rule=fix_rule):
                        updated = folio_profiles.apply_record_fix(
                            record,
                            _rule,
                            folio_context,
                        )
                        store.replace(record_no - 1, updated)
                        st.session_state.pop("issues_cache", None)

            open_record_modal(
                record_index=record_index,
                store=store,
                extra_lines=[
                    ("Message", row["message"]),
                    ("Suggestion", row.get("suggestion", "")),
                ],
                highlight_tag=tag,
                highlight_severity=row["severity"],
                fix_label=fix_label,
                on_fix=on_fix,
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
