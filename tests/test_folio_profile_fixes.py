from __future__ import annotations

from pymarc import Field, Subfield

from marcedit_web.lib import folio_profiles


def _rule(key):
    return next(rule for rule in folio_profiles.default_rules_for_tests() if rule.key == key)


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
