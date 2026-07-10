from __future__ import annotations

import pytest
from pymarc import Field, Subfield

from marcedit_web.lib import folio_profiles
from marcedit_web.lib.record_store import RecordStore


def _rule(key):
    return next(rule for rule in folio_profiles.default_rules_for_tests() if rule.key == key)


def _unsafe_remove_245_rule():
    return folio_profiles.FolioRule(
        key="folio-test-unsafe-remove-245",
        profile_key="folio-new-instance",
        label="245 removal is not a safe v1 FOLIO fix",
        severity="warning",
        target={"kind": "field", "tag": "245"},
        requirement={"kind": "forbidden"},
        fix={"operation": "remove_field", "tag": "245"},
        enabled=True,
    )


def test_apply_new_load_001_fix_removes_only_001(make_record):
    """The new-load 001 safe fix deletes the forbidden control field only."""
    record = make_record()
    rule = _rule("folio-new-load-forbidden-001")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert updated.get("001") is None
    assert updated.get("245") is not None


def test_apply_ebook_655_fix_adds_configured_field(make_record):
    """The ebook safe fix adds the exact configured local 655 field."""
    record = make_record()
    rule = _rule("folio-ebook-required-655")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    field = updated.get_fields("655")[0]
    assert list(field.indicators) == [" ", "7"]
    assert field.get_subfields("a") == ["Electronic books."]
    assert field.get_subfields("2") == ["local"]


def test_apply_barcode_suffix_fix_replaces_existing_suffix(make_record):
    """The barcode suffix fix preserves the stem and applies the configured code."""
    record = make_record()
    record.add_field(
        Field(
            tag="949",
            indicators=["\\", "\\"],
            subfields=[Subfield("b", "vendor123-XX")],
        )
    )
    rule = _rule("folio-949-barcode-suffix")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            institution_suffix="SC",
        ),
    )

    assert updated["949"].get_subfields("b") == ["vendor123-SC"]


def test_plan_record_fixes_reports_before_after_without_mutating(make_record):
    """Preview planning must not mutate records before confirmation."""
    record = make_record()
    rules = [_rule("folio-new-load-forbidden-001")]

    plans = folio_profiles.plan_record_fixes(
        record,
        rules,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
        record_index=3,
    )

    assert record.get("001") is not None
    assert len(plans) == 1
    assert plans[0].record_index == 3
    assert plans[0].rule_key == "folio-new-load-forbidden-001"
    assert "=001" in plans[0].before
    assert "=001" not in plans[0].after


def test_configured_remove_field_fix_is_limited_to_safe_001_delete(make_record):
    """Configured deletions other than new-load 001 remain check-only."""
    record = make_record()
    rule = _unsafe_remove_245_rule()
    context = folio_profiles.FolioContext(profile_key="folio-new-instance")

    issues = folio_profiles.evaluate_record(record, [rule], context)
    plans = folio_profiles.plan_record_fixes(record, [rule], context)
    updated = folio_profiles.apply_record_fix(record, rule, context)

    assert [item.issue.code for item in issues] == ["folio-test-unsafe-remove-245"]
    assert issues[0].fix_available is False
    assert plans == []
    assert updated.get("245") is not None


def test_apply_035_container_fix_adds_configured_field(make_record):
    """The 035 container-code fix writes the configured local code."""
    record = make_record()
    rule = _rule("folio-required-035-container")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            container_code="FC-ABC",
        ),
    )

    field = updated.get_fields("035")[0]
    assert list(field.indicators) == ["9", "\\"]
    assert field.get_subfields("a") == ["FC-ABC"]


def test_preview_batch_fixes_counts_without_mutating(make_record):
    """Batch preview reports compact counts and samples without changing records."""
    records = [make_record(), make_record()]
    rule = _rule("folio-new-load-forbidden-001")

    preview = folio_profiles.preview_batch_fixes(
        records,
        [rule],
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
        sample_limit=1,
    )

    assert preview.total_fixes == 2
    assert preview.affected_records == 2
    assert preview.affected_record_numbers == [1, 2]
    assert preview.by_rule == {"folio-new-load-forbidden-001": 2}
    assert len(preview.samples) == 1
    assert records[0].get("001") is not None


def test_apply_batch_fixes_to_store_replaces_changed_records(make_record, tmp_path):
    """Confirmed batch application mutates the disk-backed store records."""
    store = RecordStore.from_records(
        [make_record(), make_record()],
        tmp_dir=tmp_path,
        filename="sample.mrc",
    )
    rule = _rule("folio-new-load-forbidden-001")

    preview = folio_profiles.apply_batch_fixes_to_store(
        store,
        [rule],
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert preview.total_fixes == 2
    assert preview.affected_record_numbers == [1, 2]
    assert all(record.get("001") is None for record in store.iter_records())


def test_apply_batch_fixes_to_store_leaves_store_unchanged_on_failure(
    make_record, monkeypatch, tmp_path
):
    """Failed batch application must not leave partial safe fixes in the store."""
    store = RecordStore.from_records(
        [make_record(), make_record()],
        tmp_dir=tmp_path,
        filename="sample.mrc",
    )
    rule = _rule("folio-new-load-forbidden-001")
    original_apply = folio_profiles.apply_record_fix
    calls = 0

    def fail_on_third_fix(record, rule, context):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("simulated write failure")
        return original_apply(record, rule, context)

    monkeypatch.setattr(folio_profiles, "apply_record_fix", fail_on_third_fix)

    with pytest.raises(RuntimeError, match="simulated write failure"):
        folio_profiles.apply_batch_fixes_to_store(
            store,
            [rule],
            folio_profiles.FolioContext(profile_key="folio-new-instance"),
        )

    assert calls == 3
    assert all(record.get("001") is not None for record in store.iter_records())
