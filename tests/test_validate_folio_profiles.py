from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from marcedit_web.lib import folio_profiles
from marcedit_web.lib.errors import Issue
from marcedit_web.lib.rules import RuleSet
from marcedit_web.render import validate


class _FakeStatus:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **_kwargs):
        return None


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def iter_records(self):
        return iter(self._records)


def test_compute_issues_includes_selected_folio_profile(make_record, monkeypatch):
    """Validate includes selected FOLIO profile diagnostics in its issue list."""
    monkeypatch.setattr(validate.st, "status", lambda *_args, **_kwargs: _FakeStatus())
    monkeypatch.setattr(
        validate.folio_profiles,
        "rules_for_profile",
        lambda profile_key, include_addons=(): [
            rule
            for rule in folio_profiles.default_rules_for_tests()
            if rule.key == "folio-new-load-forbidden-001"
        ],
    )
    store = _FakeStore([make_record()])

    issues = validate._compute_issues(
        RuleSet(),
        store,
        malformed=0,
        folio_context=folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert "folio-new-load-forbidden-001" in {issue.code for issue in issues}


def test_folio_context_from_state_uses_selected_profile(monkeypatch):
    """Validate can build FOLIO context from selected Streamlit state values."""
    monkeypatch.setattr(
        validate.st,
        "session_state",
        {
            "folio_profile_key": "folio-new-instance",
            "folio_profile_addons": ["folio-ecollection-ebook"],
            "folio_container_code": "FC-ABC",
            "folio_institution_suffix": "SC",
            "folio_collection_name": "Five Colleges collection",
            "folio_score_loading": True,
            "folio_use_949": True,
            "folio_multi_institution": True,
        },
    )

    context = validate._folio_context_from_state()

    assert context == folio_profiles.FolioContext(
        profile_key="folio-new-instance",
        addons=("folio-ecollection-ebook",),
        container_code="FC-ABC",
        institution_suffix="SC",
        collection_name="Five Colleges collection",
        score_loading=True,
        use_949=True,
        multi_institution=True,
    )


def test_build_folio_context_includes_ebook_addon():
    """Validate UI helper converts selected controls into evaluator context."""
    context = validate._build_folio_context(
        profile_key="folio-new-instance",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    )

    assert context.profile_key == "folio-new-instance"
    assert context.addons == ("folio-ecollection-ebook",)
    assert context.institution_suffix == "SC"
    assert context.container_code == "FC123"


def test_build_folio_context_disabled_when_profile_blank():
    """Leaving the profile blank keeps Validate behavior unchanged."""
    assert validate._build_folio_context(
        profile_key="",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    ) is None


def test_folio_fix_availability_is_per_issue_occurrence():
    """Rows sharing a FOLIO code must not inherit another record's fix status."""
    issues = [
        Issue(
            severity="warning",
            scope="record",
            code="folio-same-code",
            message="fixable",
            record_index=1,
        ),
        Issue(
            severity="warning",
            scope="record",
            code="folio-same-code",
            message="check only",
            record_index=2,
        ),
    ]

    rows = validate._build_issue_rows(
        issues,
        fixable_issue_keys={("folio-same-code", 1)},
    )

    assert rows[0]["fix_available"] == "yes"
    assert rows[1]["fix_available"] == ""


def test_folio_fix_availability_uses_cached_validation_result(monkeypatch):
    """Render row metadata must not rescan records after validation computes it."""
    calls = 0
    issue = Issue(
        severity="warning",
        scope="record",
        code="folio-one",
        message="fixable",
        record_index=1,
    )

    def fake_evaluate_records(_records, _rules, _context):
        nonlocal calls
        calls += 1
        return [
            folio_profiles.FolioIssue(
                issue=issue,
                rule_key="folio-one",
                fix_available=True,
            )
        ]

    monkeypatch.setattr(validate.st, "status", lambda *_args, **_kwargs: _FakeStatus())
    monkeypatch.setattr(validate.preflight, "run_preflight", lambda **_kwargs: [])
    monkeypatch.setattr(validate.rules_validate, "validate_records", lambda *_args: [])
    monkeypatch.setattr(validate.load_readiness, "validate_records", lambda *_args: [])
    monkeypatch.setattr(
        validate.folio_profiles,
        "rules_for_profile",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        validate.folio_profiles,
        "evaluate_records",
        fake_evaluate_records,
    )

    result = validate._compute_validation_result(
        RuleSet(),
        _FakeStore([object()]),
        malformed=0,
        folio_context=folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )
    validate._build_issue_rows(result.issues, result.fixable_issue_keys)
    validate._build_issue_rows(result.issues, result.fixable_issue_keys)

    assert calls == 1
    assert result.fixable_issue_keys == {("folio-one", 1)}


def test_preview_to_rows_formats_rule_counts():
    """Batch preview summaries render as stable table rows."""
    preview = folio_profiles.FolioBatchPreview(
        total_fixes=3,
        affected_records=2,
        affected_record_numbers=[3, 1],
        by_rule={"folio-new-load-forbidden-001": 2, "folio-ebook-required-655": 1},
        samples=[],
    )

    rows = validate._preview_to_rows(preview)

    assert rows == [
        {"rule": "folio-ebook-required-655", "fixes": 1, "records": "1, 3"},
        {"rule": "folio-new-load-forbidden-001", "fixes": 2, "records": "1, 3"},
    ]


def test_folio_preview_state_detects_stale_revision():
    """Applying a preview requires the same store revision that was previewed."""
    context = folio_profiles.FolioContext(profile_key="folio-new-instance")
    preview = folio_profiles.FolioBatchPreview(
        total_fixes=1,
        affected_records=1,
        affected_record_numbers=[1],
        by_rule={"folio-new-load-forbidden-001": 1},
        samples=[],
    )

    state = validate._build_folio_preview_state(
        preview=preview,
        store_revision=2,
        folio_context=context,
        profile_rules=[
            rule for rule in folio_profiles.default_rules_for_tests()
            if rule.key == "folio-new-load-forbidden-001"
        ],
    )

    assert validate._folio_preview_state_is_current(
        state,
        store_revision=3,
        folio_context=context,
        profile_rules=[
            rule for rule in folio_profiles.default_rules_for_tests()
            if rule.key == "folio-new-load-forbidden-001"
        ],
    ) is False


def test_folio_preview_state_detects_current_context_and_rules():
    """Preview metadata stays valid only for the same context and rule keys."""
    context = folio_profiles.FolioContext(
        profile_key="folio-new-instance",
        addons=("folio-ecollection-ebook",),
    )
    rules = [
        rule for rule in folio_profiles.default_rules_for_tests()
        if rule.key in {"folio-new-load-forbidden-001", "folio-ebook-required-655"}
    ]
    preview = folio_profiles.FolioBatchPreview(
        total_fixes=1,
        affected_records=1,
        affected_record_numbers=[1],
        by_rule={"folio-new-load-forbidden-001": 1},
        samples=[],
    )

    state = validate._build_folio_preview_state(
        preview=preview,
        store_revision=2,
        folio_context=context,
        profile_rules=rules,
    )

    assert validate._folio_preview_state_is_current(
        state,
        store_revision=2,
        folio_context=context,
        profile_rules=list(reversed(rules)),
    ) is True
    assert validate._folio_preview_state_is_current(
        state,
        store_revision=2,
        folio_context=folio_profiles.FolioContext(profile_key="folio-new-instance"),
        profile_rules=rules,
    ) is False


def test_find_single_folio_fix_rule_returns_matching_rule(make_record):
    """Validate can map a selected FOLIO issue back to one safe fix rule."""
    rules = [
        rule for rule in folio_profiles.default_rules_for_tests()
        if rule.key == "folio-new-load-forbidden-001"
    ]
    rule = validate._find_single_folio_fix_rule(
        make_record(),
        "folio-new-load-forbidden-001",
        rules,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert rule.key == "folio-new-load-forbidden-001"


def test_record_folio_snapshot_records_safe_fix_provenance(monkeypatch, tmp_path):
    """FOLIO fixes must create History provenance under the active job."""
    staged_path = tmp_path / "after.mrc"
    calls = []

    @contextmanager
    def fake_staged_store_path(store):
        calls.append(("stage", store))
        yield staged_path

    def fake_record_edit_snapshot(**kwargs):
        calls.append(("snapshot", kwargs))

    monkeypatch.setattr(validate.st, "session_state", {"current_job_id": 12})
    monkeypatch.setattr(validate.session, "current_user_id", lambda: "user@example.org")
    monkeypatch.setattr(
        validate,
        "snapshot_actions",
        SimpleNamespace(
            staged_store_path=fake_staged_store_path,
            record_edit_snapshot=fake_record_edit_snapshot,
        ),
        raising=False,
    )
    store = object()

    validate._record_folio_snapshot(
        store,
        label="FOLIO safe fix",
        summary={
            "rule": "folio-new-load-forbidden-001",
            "record_index": 2,
            "mode": "single-record",
        },
    )

    assert calls == [
        ("stage", store),
        (
            "snapshot",
            {
                "job_id": 12,
                "user_email": "user@example.org",
                "label": "FOLIO safe fix",
                "after_path": staged_path,
                "record_index": None,
                "source": "folio-safe-fix",
                "summary": {
                    "rule": "folio-new-load-forbidden-001",
                    "record_index": 2,
                    "mode": "single-record",
                },
            },
        ),
    ]
