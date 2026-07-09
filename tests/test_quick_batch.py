"""Tests for deterministic quick batch operations (TASK-137)."""

from __future__ import annotations

import pymarc
import pytest

from marcedit_web.lib.quick_batch import (
    QuickBatchRequest,
    apply_preview,
    apply_request,
    build_preview,
    validate_request,
)
from marcedit_web.lib.record_store import RecordStore


def _store(tmp_path, *records):
    return RecordStore.from_records(
        list(records),
        tmp_dir=tmp_path / "records",
        filename="quick-batch.mrc",
    )


def _record(*fields):
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data="test-record"))
    for field in fields:
        record.add_field(field)
    return record


def _field(tag, *pairs, ind1=" ", ind2=" "):
    return pymarc.Field(
        tag=tag,
        indicators=[ind1, ind2],
        subfields=[pymarc.Subfield(code, value) for code, value in pairs],
    )


def test_leader_request_sets_safe_position_on_every_record(tmp_path):
    store = _store(tmp_path, _record(), _record())
    request = QuickBatchRequest(kind="leader", position="05", value="c")

    preview = build_preview(store, request)

    assert preview.error is None
    assert preview.changed_count == 2
    assert [str(record.leader)[5] for record in preview.output_records] == ["c", "c"]
    assert [str(record.leader)[5] for record in store.iter_records()] == ["n", "n"]


def test_leader_request_rejects_structural_position():
    request = QuickBatchRequest(kind="leader", position="09", value="a")

    assert "not available" in (validate_request(request) or "")


def test_008_form_request_updates_known_position_and_skips_missing_008(tmp_path):
    with_008 = _record(pymarc.Field(tag="008", data="180706s2013    nyu     ob    001 0 eng d"))
    without_008 = _record()
    store = _store(tmp_path, with_008, without_008)
    request = QuickBatchRequest(kind="008-form", value="q")

    preview = build_preview(store, request)

    assert preview.changed_count == 1
    assert preview.skipped_count == 1
    assert preview.output_records[0].get("008").data[23] == "q"


def test_040_cleanup_adds_rda_and_local_modifier_without_duplicates(tmp_path):
    record = _record(_field("040", ("a", "MiU"), ("b", "eng"), ("e", "rda"), ("d", "MiU")))
    store = _store(tmp_path, record)
    request = QuickBatchRequest(kind="040-cleanup", agency="MiU")

    preview = build_preview(store, request)

    field = preview.output_records[0].get("040")
    assert preview.changed_count == 0
    assert field.get_subfields("e") == ["rda"]
    assert field.get_subfields("d") == ["MiU"]


def test_040_cleanup_creates_missing_field(tmp_path):
    store = _store(tmp_path, _record())
    request = QuickBatchRequest(kind="040-cleanup", agency="MiU")

    preview = build_preview(store, request)

    field = preview.output_records[0].get("040")
    assert preview.changed_count == 1
    assert field.get_subfields("e") == ["rda"]
    assert field.get_subfields("d") == ["MiU"]


def test_856_add_proxy_only_updates_unproxied_urls(tmp_path):
    prefix = "https://proxy.example/login?url="
    record = _record(
        _field("856", ("u", "https://vendor.example/book")),
        _field("856", ("u", f"{prefix}https://vendor.example/already")),
    )
    store = _store(tmp_path, record)
    request = QuickBatchRequest(
        kind="856-url",
        action="add-proxy",
        url_contains="vendor.example",
        proxy_prefix=prefix,
    )

    preview = build_preview(store, request)

    urls = [
        value
        for field in preview.output_records[0].get_fields("856")
        for value in field.get_subfields("u")
    ]
    assert preview.changed_count == 1
    assert urls == [
        f"{prefix}https://vendor.example/book",
        f"{prefix}https://vendor.example/already",
    ]


def test_856_remove_proxy_strips_existing_prefix(tmp_path):
    prefix = "https://proxy.example/login?url="
    record = _record(_field("856", ("u", f"{prefix}https://vendor.example/book")))
    store = _store(tmp_path, record)
    request = QuickBatchRequest(kind="856-url", action="remove-proxy", proxy_prefix=prefix)

    preview = build_preview(store, request)

    assert preview.changed_count == 1
    assert preview.output_records[0].get("856")["u"] == "https://vendor.example/book"


def test_856_delete_matching_url_removes_matching_fields(tmp_path):
    record = _record(
        _field("856", ("u", "https://vendor.example/book")),
        _field("856", ("u", "https://keep.example/book")),
    )
    store = _store(tmp_path, record)
    request = QuickBatchRequest(
        kind="856-url",
        action="delete-matching",
        url_contains="vendor.example",
    )

    preview = build_preview(store, request)

    assert preview.changed_count == 1
    assert preview.output_records[0].get("856")["u"] == "https://keep.example/book"
    assert preview.detail_counts == {"856 removed: https://vendor.example/book": 1}


def test_035_oclc_cleanup_normalizes_duplicates_and_preserves_035_9(tmp_path):
    record = _record(
        _field("035", ("a", "(OCoLC)ocn123")),
        _field("035", ("a", "(OCoLC)123")),
        _field("035", ("9", "(FCMUSEOA)")),
    )
    store = _store(tmp_path, record)
    request = QuickBatchRequest(kind="035-oclc")

    preview = build_preview(store, request)

    fields = preview.output_records[0].get_fields("035")
    assert preview.changed_count == 1
    assert [field.get_subfields("a") for field in fields] == [["(OCoLC)123"], []]
    assert fields[1].get_subfields("9") == ["(FCMUSEOA)"]


def test_035_oclc_cleanup_preserves_attached_035_9_on_duplicate(tmp_path):
    record = _record(
        _field("035", ("a", "(OCoLC)123")),
        _field("035", ("a", "(OCoLC)ocn000123"), ("9", "(FCMUSEOA)")),
    )
    store = _store(tmp_path, record)

    preview = build_preview(store, QuickBatchRequest(kind="035-oclc"))

    fields = preview.output_records[0].get_fields("035")
    assert fields[0].get_subfields("a") == ["(OCoLC)123"]
    assert fields[1].get_subfields("a") == []
    assert fields[1].get_subfields("9") == ["(FCMUSEOA)"]


def test_035_oclc_cleanup_keeps_distinct_oclc_values_in_one_field(tmp_path):
    record = _record(_field("035", ("a", "(OCoLC)123"), ("z", "(OCoLC)456")))
    store = _store(tmp_path, record)

    preview = build_preview(store, QuickBatchRequest(kind="035-oclc"))

    field = preview.output_records[0].get("035")
    assert field.get_subfields("a") == ["(OCoLC)123"]
    assert field.get_subfields("z") == ["(OCoLC)456"]


def test_9xx_delete_exact_tag_and_range(tmp_path):
    exact = _store(
        tmp_path / "exact",
        _record(_field("949", ("a", "delete")), _field("950", ("a", "keep"))),
    )
    range_store = _store(
        tmp_path / "range",
        _record(_field("949", ("a", "delete")), _field("950", ("a", "delete"))),
    )

    exact_preview = build_preview(exact, QuickBatchRequest(kind="9xx-delete", tag="949"))
    range_preview = build_preview(
        range_store,
        QuickBatchRequest(kind="9xx-delete", tag="9XX"),
    )

    assert [field.tag for field in exact_preview.output_records[0].fields] == ["001", "950"]
    assert exact_preview.detail_counts == {"949 removed": 1}
    assert range_preview.output_records[0].get_fields("949", "950") == []
    assert range_preview.detail_counts == {"949 removed": 1, "950 removed": 1}


def test_655_cleanup_adds_standard_field_and_deletes_unwanted_text(tmp_path):
    record = _record(_field("655", ("a", "Electronic books."), ("2", "local"), ind2="7"))
    store = _store(tmp_path, record)
    request = QuickBatchRequest(
        kind="655-cleanup",
        genre_term="Electronic books.",
        genre_source="lcgft",
        unwanted_text="Electronic books.",
    )

    preview = build_preview(store, request)

    fields = preview.output_records[0].get_fields("655")
    assert preview.changed_count == 1
    assert len(fields) == 1
    assert fields[0].get_subfields("a") == ["Electronic books."]
    assert fields[0].get_subfields("2") == ["lcgft"]
    assert preview.detail_counts == {"655 removed: Electronic books.": 1}


def test_build_preview_reports_changed_and_skipped_counts(tmp_path):
    store = _store(tmp_path, _record(), _record())
    request = QuickBatchRequest(kind="leader", position="05", value="n")

    preview = build_preview(store, request)

    assert preview.changed_count == 0
    assert preview.skipped_count == 2


def test_apply_request_replaces_store_records(tmp_path):
    store = _store(tmp_path, _record())
    result = apply_request(store, QuickBatchRequest(kind="leader", position="05", value="c"))

    assert result.applied
    assert result.changed_count == 1
    assert str(store.get(0).leader)[5] == "c"


def test_apply_preview_refuses_stale_store(tmp_path):
    store = _store(tmp_path, _record())
    preview = build_preview(store, QuickBatchRequest(kind="leader", position="05", value="c"))
    store.replace(0, _record(_field("245", ("a", "External edit."))))

    result = apply_preview(store, preview)

    assert not result.applied
    assert "changed since preview" in (result.error or "")
    assert str(store.get(0).leader)[5] == "n"


@pytest.mark.parametrize(
    "quick_request, message",
    [
        (QuickBatchRequest(kind="856-url", action="add-proxy", proxy_prefix=""), "Proxy prefix"),
        (QuickBatchRequest(kind="9xx-delete", tag="856"), "9XX"),
        (QuickBatchRequest(kind="655-cleanup", genre_term="", genre_source="lcgft"), "Genre"),
    ],
)
def test_validate_request_rejects_incomplete_operations(quick_request, message):
    assert message in (validate_request(quick_request) or "")
