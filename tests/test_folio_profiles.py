from __future__ import annotations

from pymarc import Field, Subfield

from marcedit_web.lib import folio_profiles


def _rules(*keys):
    all_rules = folio_profiles.default_rules_for_tests()
    return [rule for rule in all_rules if rule.key in set(keys)]


def test_new_load_flags_001_with_safe_fix(make_record):
    """New FOLIO Instance/SRS loads must not carry a source 001."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-new-load-forbidden-001"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert [item.issue.code for item in issues] == ["folio-new-load-forbidden-001"]
    assert issues[0].fix_available is True
    assert issues[0].issue.record_index == 1


def test_roundtrip_flags_missing_001_without_fix(make_record):
    """Round-trip records need 001 because it preserves the Instance/SRS link."""
    record = make_record()
    record.remove_fields("001")

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-roundtrip-required-001"),
        folio_profiles.FolioContext(profile_key="folio-round-trip"),
    )

    assert [item.issue.code for item in issues] == ["folio-roundtrip-required-001"]
    assert issues[0].fix_available is False
    assert issues[0].issue.severity == "error"


def test_ebook_profile_flags_missing_655_with_safe_fix(make_record):
    """The ebook add-on can add the configured local Electronic books term."""
    record = make_record()
    record.remove_fields("655")

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-ebook-required-655"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            addons=("folio-ecollection-ebook",),
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-ebook-required-655"]
    assert issues[0].fix_available is True


def test_ebook_rule_does_not_fire_without_addon(make_record):
    """Add-on rules only apply when the add-on is selected in context."""
    record = make_record()
    record.remove_fields("655")

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-ebook-required-655"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert issues == []


def test_008_byte_29_rejects_government_document_values(make_record):
    """008 byte 29 values s/z/o are unsafe for EDS display."""
    record = make_record()
    data = list(record["008"].data)
    data[29] = "s"
    record["008"].data = "".join(data)

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-008-byte-29-not-govdoc"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert [item.issue.code for item in issues] == ["folio-008-byte-29-not-govdoc"]
    assert issues[0].fix_available is False


def test_loading_path_accepts_valid_949(make_record):
    """A complete 949 path satisfies the either/or FOLIO loading-path rule."""
    record = make_record()
    record.add_field(
        Field(
            tag="949",
            indicators=["\\", "\\"],
            subfields=[
                Subfield("u", "https://example.test/book"),
                Subfield("y", "Connect to resource"),
                Subfield("t", "ONLINE"),
                Subfield("p", "EBOOK"),
                Subfield("h", "EBOOK"),
                Subfield("l", "elec"),
                Subfield("b", "barcode-SC"),
                Subfield("m", "sc"),
            ],
        )
    )

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-loading-path-required"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert issues == []


def test_barcode_suffix_rule_uses_configured_suffix(make_record):
    """949 $b must end in the configured institution suffix."""
    record = make_record()
    record.add_field(
        Field(
            tag="949",
            indicators=["\\", "\\"],
            subfields=[Subfield("b", "barcode-XX")],
        )
    )

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-949-barcode-suffix"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            institution_suffix="SC",
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-949-barcode-suffix"]
    assert issues[0].fix_available is True
