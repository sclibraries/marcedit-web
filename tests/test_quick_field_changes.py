from __future__ import annotations

from dataclasses import asdict

import pytest
from pymarc import Field, Record, Subfield

from marcedit_web.lib.quick_field_changes import (
    QuickFieldChangeRequest,
    RecordChangeResult,
    apply_quick_field_change,
    prepare_quick_field_change_adapter,
    request_from_payload,
    request_to_payload,
    validate_request,
)
from marcedit_web.lib import transforms
from marcedit_web.lib.quick_field_selector import FieldFilter, FieldSelector, Occurrence


def _field(tag: str, ind1: str = " ", ind2: str = " ", *subfields, data=None):
    if data is not None:
        return Field(tag=tag, data=data)
    return Field(tag=tag, indicators=[ind1, ind2], subfields=[Subfield(c, v) for c, v in subfields])


def _record(*fields):
    record = Record()
    record.add_ordered_field(*fields)
    return record


def _selector(tag="856", *, mode="first", number=None, **kwargs):
    return FieldSelector(FieldFilter(tag=tag, **kwargs), Occurrence(mode, number))


def test_payload_round_trip_is_json_compatible_and_immutable():
    request = QuickFieldChangeRequest(
        "add-field",
        destination_tag="245",
        ind1="1",
        ind2="0",
        subfields=(("a", "Title"),),
    )
    payload = request_to_payload(request)
    assert payload["subfields"] == [["a", "Title"]]
    assert request_from_payload(payload) == request
    assert validate_request(request) == ()


@pytest.mark.parametrize(
    "request_value",
    [
        QuickFieldChangeRequest("add-field", destination_tag="000", ind1=" ", ind2=" "),
        QuickFieldChangeRequest("add-subfield", _selector("001"), subfield_code="a", subfield_value="x"),
        QuickFieldChangeRequest("set-indicators", _selector("856")),
        QuickFieldChangeRequest("copy-field", _selector("856"), destination_tag="001"),
    ],
)
def test_invalid_requests_fail_closed(request_value):
    assert validate_request(request_value)
    with pytest.raises(ValueError):
        apply_quick_field_change(_record(), request_value)


def test_add_field_control_and_scope_policies():
    record = _record(_field("001", data="one"))
    request = QuickFieldChangeRequest("add-field", destination_tag="001", control_value="two", record_scope="tag_absent")
    assert apply_quick_field_change(record, request).changed is False
    request = QuickFieldChangeRequest("add-field", destination_tag="002", control_value="two")
    result = apply_quick_field_change(record, request)
    assert result.fields_affected == 1
    assert record.get("002").data == "two"


def test_add_field_data_identical_suppression_and_subfield_limit():
    record = _record(_field("245", "1", "0", ("a", "Title")))
    request = QuickFieldChangeRequest("add-field", destination_tag="245", ind1="1", ind2="0", subfields=(("a", "Title"),), record_scope="identical_absent")
    assert apply_quick_field_change(record, request).changed is False
    too_many = QuickFieldChangeRequest("add-field", destination_tag="245", ind1="1", ind2="0", subfields=tuple(("a", str(i)) for i in range(101)))
    assert any("100" in error for error in validate_request(too_many))


@pytest.mark.parametrize(
    "request_value",
    [
        QuickFieldChangeRequest("add-subfield", _selector(), subfield_code="9", position="start"),
        QuickFieldChangeRequest("add-subfield", _selector(), subfield_code="9", repeat_policy="skip"),
        QuickFieldChangeRequest("add-field", destination_tag="245", ind1="1", ind2="0", record_scope="when_tag_absent"),
        QuickFieldChangeRequest("copy-field", _selector(), destination_tag="956", destination_policy="replace-all"),
    ],
)
def test_request_enums_are_fail_closed(request_value):
    assert validate_request(request_value)


def test_payload_rejects_non_row_subfield_values():
    payload = request_to_payload(
        QuickFieldChangeRequest("add-field", destination_tag="245", ind1="1", ind2="0")
    )
    for rows in ({"a": "b", "x": "y"}, [["a"]], [["a", 1]]):
        payload["subfields"] = rows
        with pytest.raises(ValueError):
            request_from_payload(payload)


@pytest.mark.parametrize(
    "value, message",
    [("x" * 1025, "1,024"), ("€" * 1024, "2,048")],
)
def test_delete_subfield_matcher_obeys_selector_size_bounds(value, message):
    request = QuickFieldChangeRequest(
        "delete-subfield", _selector(), subfield_code="u", subfield_value=value
    )
    assert any(message in error for error in validate_request(request))


def test_data_identical_scope_uses_shared_add_helper(monkeypatch):
    record = _record(_field("245", "1", "0", ("a", "Existing")))
    original = transforms.add_field_if_absent
    calls = []

    def wrapped(current_record, field):
        calls.append(field)
        return original(current_record, field)

    monkeypatch.setattr(transforms, "add_field_if_absent", wrapped)
    request = QuickFieldChangeRequest(
        "add-field",
        destination_tag="245",
        ind1="1",
        ind2="0",
        subfields=(("a", "New"),),
        record_scope="identical_absent",
    )
    assert apply_quick_field_change(record, request).changed
    assert len(calls) == 1


def test_add_and_delete_subfield_are_occurrence_scoped():
    first = _field("856", "4", "0", ("u", "one"))
    second = _field("856", "4", "0", ("u", "two"))
    record = _record(first, second)
    assert apply_quick_field_change(record, QuickFieldChangeRequest("add-subfield", _selector(mode="first"), subfield_code="9", subfield_value="x")).changed
    assert first.get_subfields("9") == ["x"]
    assert second.get_subfields("9") == []
    request = QuickFieldChangeRequest("delete-subfield", _selector(mode="first"), subfield_code="u", subfield_value="one", subfield_occurrence="first")
    assert apply_quick_field_change(record, request).subfields_affected == 1
    assert first.get_subfields("u") == []
    assert second.get_subfields("u") == ["two"]


def test_delete_subfield_can_remove_empty_field_explicitly():
    record = _record(_field("856", "4", "0", ("u", "one")))
    request = QuickFieldChangeRequest("delete-subfield", _selector(), subfield_code="u", remove_empty_field=True)
    result = apply_quick_field_change(record, request)
    assert result.changed is True
    assert result.fields_affected == 1
    assert record.get_fields("856") == []


def test_copy_is_deep_and_replace_all_is_source_safe():
    source = _field("856", "4", "0", ("u", "one"))
    destination = _field("956", "4", "0", ("u", "old"))
    record = _record(source, destination)
    request = QuickFieldChangeRequest("copy-field", _selector(), destination_tag="956", destination_policy="replace_all")
    assert apply_quick_field_change(record, request).changed
    copied = record.get_fields("956")[0]
    assert copied is not source and copied.tag == "956"
    copied.subfields = [Subfield("u", "changed")]
    assert record.get_fields("856")[0].get_subfields("u") == ["one"]
    absent = _record(destination)
    assert apply_quick_field_change(absent, request).skipped
    assert absent.get_fields("956")[0] is destination


def test_copy_replace_all_identical_destination_is_unchanged():
    source = _field("856", "4", "0", ("u", "same"))
    destination = _field("956", "4", "0", ("u", "same"))
    record = _record(source, destination)
    request = QuickFieldChangeRequest(
        "copy-field",
        _selector("856"),
        destination_tag="956",
        destination_policy="replace_all",
    )

    result = apply_quick_field_change(record, request)

    assert result.changed is False
    assert result.fields_affected == 0
    assert [field.tag for field in record.fields] == ["856", "956"]


def test_move_retags_selected_object_in_place_and_preserves_position():
    source = _field("856", "4", "0", ("u", "one"))
    middle = _field("245", "1", "0", ("a", "title"))
    record = _record(source, middle)
    request = QuickFieldChangeRequest("move-field", _selector(), destination_tag="956")
    result = apply_quick_field_change(record, request)
    assert result.changed and record.fields[1].tag == "956" and record.fields[1] is not middle
    assert record.fields[1] is record.get_fields("956")[0]


def test_set_indicators_distinguishes_none_from_marc_blank():
    field = _field("245", "1", "0", ("a", "title"))
    record = _record(field)
    assert apply_quick_field_change(record, QuickFieldChangeRequest("set-indicators", _selector("245"), ind1=" ")).changed
    assert list(field.indicators) == [" ", "0"]
    assert apply_quick_field_change(record, QuickFieldChangeRequest("set-indicators", _selector("245"), ind1=None, ind2=" ")).changed
    assert list(field.indicators) == [" ", " "]


def test_swap_uses_two_filters_and_skips_same_object():
    first = _field("070", " ", " ", ("a", "Kanopy feature"))
    second = _field("070", " ", " ", ("a", "Kanopy collection"))
    record = _record(first, second)
    request = QuickFieldChangeRequest(
        "swap-field-occurrences",
        _selector("070", subfield_code="a", match_mode="contains", match_value="feature"),
        _selector("070", subfield_code="a", match_mode="contains", match_value="collection"),
    )
    assert apply_quick_field_change(record, request).changed
    assert record.fields == [second, first]
    same = QuickFieldChangeRequest("swap-field-occurrences", _selector("070"), _selector("070", mode="last"))
    assert apply_quick_field_change(_record(first), same).skipped


def test_swap_distinct_identical_fields_is_unchanged():
    first = _field("070", " ", " ", ("a", "same"))
    second = _field("070", " ", " ", ("a", "same"))
    record = _record(first, second)
    request = QuickFieldChangeRequest(
        "swap-field-occurrences",
        _selector("070", mode="first"),
        _selector("070", mode="last"),
    )

    result = apply_quick_field_change(record, request)

    assert result.changed is False
    assert result.fields_affected == 0


def test_remove_exact_duplicates_keeps_stable_first_or_last():
    one = _field("245", "1", "0", ("a", "same"))
    two = _field("245", "1", "0", ("a", "same"))
    different_order = _field("245", "1", "0", ("b", "same"), ("a", "same"))
    record = _record(one, two, different_order)
    request = QuickFieldChangeRequest("remove-duplicate-fields", duplicate_filter=FieldFilter("245"), keep_duplicate="last")
    result = apply_quick_field_change(record, request)
    assert result.fields_affected == 1
    assert record.fields == [two, different_order]


def test_adapter_validates_once_and_returns_bounded_result_shape():
    payload = request_to_payload(QuickFieldChangeRequest("delete-field", _selector("245")))
    adapter = prepare_quick_field_change_adapter(payload)
    result = adapter(_record(_field("245", "1", "0", ("a", "title"))))
    assert result == asdict(RecordChangeResult(True, fields_affected=1))
