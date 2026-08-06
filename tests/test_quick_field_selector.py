import pytest
from pymarc import Field, Record, Subfield

from marcedit_web.lib.quick_field_selector import (
    FieldFilter,
    FieldSelector,
    IndicatorFilter,
    Occurrence,
    describe_selector,
    matching_fields,
    resolve_fields,
    validate_field_filter,
    validate_selector,
)


def _field(tag, ind1, ind2, *subfields, data=None):
    if data is not None:
        return Field(tag=tag, data=data)
    return Field(
        tag=tag,
        indicators=[ind1, ind2],
        subfields=[Subfield(code, value) for code, value in subfields],
    )


def _record(*fields):
    record = Record()
    record.add_ordered_field(*fields)
    return record


def _selector(**filter_values):
    return FieldSelector(field_filter=FieldFilter(**filter_values))


def test_filter_then_occurrence_numbers_only_filtered_fields():
    record = _record(
        _field("856", "4", "0", ("u", "https://other.example/a")),
        _field("856", "4", "0", ("u", "https://kanopy.com/one")),
        _field("856", "4", "0", ("u", "https://kanopy.com/two")),
    )
    selector = FieldSelector(
        field_filter=FieldFilter(
            tag="856",
            subfield_code="u",
            match_mode="contains",
            match_value="kanopy.com",
        ),
        occurrence=Occurrence(mode="numbered", number=2),
    )

    result = resolve_fields(record, selector)

    assert result.fields == (record.fields[2],)
    assert result.skip_reason is None


def test_exact_tag_filter_does_not_widen_when_record_has_zero_matching_fields():
    record = _record(_field("070", " ", " ", ("a", "class number")))

    result = resolve_fields(record, _selector(tag="856"))

    assert result.fields == ()
    assert result.skip_reason == "no-filtered-fields"


@pytest.mark.parametrize(
    ("mode", "value", "expected_indexes"),
    [
        ("any", "", (0, 1, 2)),
        ("blank", "", (1, 2)),
        ("exact", "4", (0,)),
    ],
)
def test_indicator_filters_select_data_fields(mode, value, expected_indexes):
    record = _record(
        _field("070", "4", "0", ("a", "one")),
        _field("070", " ", "0", ("a", "two")),
        _field("070", " ", "1", ("a", "three")),
    )

    result = matching_fields(
        record,
        FieldFilter(
            tag="070",
            ind1=IndicatorFilter(mode=mode, value=value),
        ),
    )

    assert tuple(record.fields.index(field) for field in result) == expected_indexes


@pytest.mark.parametrize("mode", [[], {}])
def test_indicator_validation_rejects_unhashable_modes_without_raising(mode):
    field_filter = FieldFilter(
        tag="856",
        ind1=IndicatorFilter(mode=mode),
    )

    errors = validate_field_filter(field_filter)

    assert any("indicator 1 mode" in error for error in errors)


@pytest.mark.parametrize(
    ("match_mode", "match_value", "ignore_case", "expected"),
    [
        ("exact", "Kanopy", False, (0,)),
        ("contains", "nOp", False, ()),
        ("contains", "nOp", True, (0, 1)),
        ("starts_with", "kan", True, (0, 1)),
        ("ends_with", "OPY", True, (0,)),
    ],
)
def test_guided_text_modes_and_case_choice(
    match_mode, match_value, ignore_case, expected
):
    record = _record(
        _field("856", "4", "0", ("u", "Kanopy")),
        _field("856", "4", "0", ("u", "Kanopy catalog")),
        _field("856", "4", "0", ("u", "Other")),
    )

    result = matching_fields(
        record,
        FieldFilter(
            tag="856",
            subfield_code="u",
            match_mode=match_mode,
            match_value=match_value,
            ignore_case=ignore_case,
        ),
    )

    assert tuple(record.fields.index(field) for field in result) == expected


def test_raw_regex_is_supported_by_matching_fields():
    record = _record(
        _field("856", "4", "0", ("u", "https://kanopy.com/one")),
        _field("856", "4", "0", ("u", "https://other.example/two")),
    )

    result = matching_fields(
        record,
        FieldFilter(
            tag="856",
            subfield_code="u",
            match_mode="raw_regex",
            match_value=r"^https://kanopy\.com/",
        ),
    )

    assert result == (record.fields[0],)


@pytest.mark.parametrize(
    ("mode", "number", "expected"),
    [
        ("first", None, (0,)),
        ("last", None, (3,)),
        ("every", None, (0, 2, 3)),
        ("numbered", 2, (2,)),
    ],
)
def test_occurrence_modes_apply_after_filtering(mode, number, expected):
    record = _record(
        _field("856", "4", "0", ("u", "kanopy one")),
        _field("856", "4", "0", ("u", "other")),
        _field("856", "4", "0", ("u", "kanopy two")),
        _field("856", "4", "0", ("u", "kanopy three")),
    )
    selector = FieldSelector(
        field_filter=FieldFilter(
            tag="856", subfield_code="u", match_mode="contains", match_value="kanopy"
        ),
        occurrence=Occurrence(mode=mode, number=number),
    )

    result = resolve_fields(record, selector)

    assert tuple(record.fields.index(field) for field in result.fields) == expected


@pytest.mark.parametrize(
    ("occurrence", "reason"),
    [
        (Occurrence(mode="first"), "no-filtered-fields"),
        (Occurrence(mode="last"), "no-filtered-fields"),
        (Occurrence(mode="every"), "no-filtered-fields"),
        (Occurrence(mode="numbered", number=2), "numbered-occurrence-absent"),
    ],
)
def test_absent_occurrences_return_stable_reason_codes(occurrence, reason):
    record = _record(_field("856", "4", "0", ("u", "one")))
    match_value = "one" if occurrence.mode == "numbered" else "missing"
    selector = FieldSelector(
        field_filter=FieldFilter(
            tag="856", subfield_code="u", match_value=match_value
        ),
        occurrence=occurrence,
    )

    result = resolve_fields(record, selector)

    assert result.fields == ()
    assert result.skip_reason == reason


@pytest.mark.parametrize(
    ("filter_value", "message"),
    [
        (FieldFilter(tag="000"), "000"),
        (FieldFilter(tag="85"), "three"),
        (FieldFilter(tag="856", subfield_code="uu"), "one lowercase"),
        (FieldFilter(tag="856", subfield_code="u", match_value=""), "nonempty"),
        (FieldFilter(tag="856", match_mode="near"), "mode"),
    ],
)
def test_field_filter_validation_rejects_invalid_values(filter_value, message):
    assert any(message in error for error in validate_field_filter(filter_value))


def test_control_fields_reject_indicator_and_subfield_filters():
    control = _field("001", "", "", data="abc")

    with pytest.raises(ValueError, match="control field"):
        matching_fields(
            _record(control),
            FieldFilter(tag="001", ind1=IndicatorFilter(mode="blank")),
        )
    with pytest.raises(ValueError, match="control field"):
        matching_fields(
            _record(control),
            FieldFilter(tag="001", subfield_code="a", match_value="x"),
        )


def test_invalid_raw_regex_is_reported_at_matching_boundary():
    with pytest.raises(ValueError, match="regular expression"):
        matching_fields(
            _record(_field("856", "4", "0", ("u", "value"))),
            FieldFilter(
                tag="856",
                subfield_code="u",
                match_mode="raw_regex",
                match_value="(",
            ),
        )


@pytest.mark.parametrize("number", [0, -1, 1000, True, None])
def test_numbered_occurrence_is_bounded_to_one_through_999(number):
    occurrence = Occurrence(mode="numbered", number=number)
    errors = validate_selector(
        FieldSelector(field_filter=FieldFilter(tag="856"), occurrence=occurrence)
    )
    assert errors
    if number is None:
        assert any("number" in error for error in errors)


def test_every_can_be_rejected_for_single_field_operations():
    errors = validate_selector(
        FieldSelector(
            field_filter=FieldFilter(tag="856"),
            occurrence=Occurrence(mode="every"),
        ),
        allow_every=False,
    )

    assert any("every" in error.lower() for error in errors)


def test_describe_selector_is_plain_language_and_deterministic():
    selector = FieldSelector(
        field_filter=FieldFilter(
            tag="856",
            ind1=IndicatorFilter(mode="exact", value="4"),
            ind2=IndicatorFilter(mode="blank"),
            subfield_code="u",
            match_mode="starts_with",
            match_value="HTTPS://",
            ignore_case=True,
        ),
        occurrence=Occurrence(mode="numbered", number=2),
    )

    assert describe_selector(selector) == (
        "856 fields where indicator 1 is '4', indicator 2 is MARC blank, "
        "subfield $u starts with 'HTTPS://' (case-insensitive); select numbered "
        "occurrence 2"
    )
