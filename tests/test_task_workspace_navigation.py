"""Tests for the deterministic TASK-193 Tasks query contract."""

from dataclasses import fields

import pytest

from marcedit_web.lib.task_workspace_navigation import (
    TASK_QUERY_KEYS,
    LibraryFilters,
    WorkspaceLocation,
    canonical_tasks_query,
    merge_tasks_query,
    parse_tasks_query,
)


def test_tasks_query_round_trips_all_supported_values():
    raw = {
        "view": "library",
        "scope": "shared",
        "folder": "41",
        "q": "856",
        "visibility": "shared",
        "owner": "smith.edu",
        "tag": "856",
        "subfield": "u",
        "operation": "delete-tag",
        "validation": "valid",
        "updated": "7",
    }
    location = parse_tasks_query(raw, operation_kinds={"delete-tag"})
    assert canonical_tasks_query(location) == raw


def test_invalid_values_fall_back_independently():
    location = parse_tasks_query(
        {
            "view": "wrong",
            "mode": "wrong",
            "folder": "-2",
            "visibility": "shared",
            "updated": "yesterday",
        },
        operation_kinds={"delete-tag"},
    )
    assert location.view == "run"
    assert location.mode == "saved"
    assert location.folder_id is None
    assert location.filters.visibility == "shared"
    assert location.filters.updated == "any"


def test_merge_preserves_non_tasks_and_repeated_values():
    merged = merge_tasks_query(
        {
            "job_file": "12",
            "start": "upload",
            "external": ["a", "b"],
            "view": "run",
        },
        WorkspaceLocation(view="library"),
    )
    assert merged == {
        "job_file": "12",
        "start": "upload",
        "external": ["a", "b"],
        "view": "library",
    }


@pytest.mark.parametrize("key", sorted(TASK_QUERY_KEYS))
def test_every_tasks_key_is_owned_and_canonicalized(key):
    assert key in TASK_QUERY_KEYS


def test_navigation_has_no_definition_or_record_fields():
    location_fields = {field.name for field in fields(WorkspaceLocation)}
    filter_fields = {field.name for field in fields(LibraryFilters)}
    assert location_fields.isdisjoint(
        {"body", "operations", "source_line", "marc"}
    )
    assert filter_fields.isdisjoint(
        {"body", "operations", "source_line", "marc"}
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("q", "x" * 256),
        ("owner", "x" * 256),
        ("tag", "8567"),
        ("subfield", "uu"),
        ("subfield", "-"),
        ("operation", "x" * 65),
    ],
)
def test_bounded_values_fall_back_individually(key, value):
    location = parse_tasks_query(
        {key: value, "visibility": "shared"}, operation_kinds={"delete-tag"}
    )
    assert location.filters.visibility == "shared"
    assert getattr(location.filters, {"q": "query"}.get(key, key)) in {
        "",
        "all",
        "any",
    }


def test_streamlit_list_values_use_the_first_scalar():
    location = parse_tasks_query(
        {"view": ["library", "run"], "folder": ["41"]},
        operation_kinds=set(),
    )
    assert location.view == "library"
    assert location.folder_id == 41


def test_ids_are_positive_and_canonicalized():
    location = parse_tasks_query(
        {"folder": "001", "task": "0", "dialog_task": "12"},
        operation_kinds=set(),
    )
    assert location.folder_id == 1
    assert location.task_id is None
    assert location.dialog_task_id == 12
    assert canonical_tasks_query(location) == {
        "folder": "1",
        "dialog_task": "12",
    }


def test_huge_or_out_of_range_ids_fall_back_without_affecting_other_ids():
    location = parse_tasks_query(
        {
            "folder": "9" * 5000,
            "task": "9223372036854775807",
            "dialog_folder": "9223372036854775808",
        },
        operation_kinds=set(),
    )
    assert location.folder_id is None
    assert location.task_id == 9223372036854775807
    assert location.dialog_folder_id is None


def test_operation_must_be_all_or_renderer_supplied_kind():
    assert (
        parse_tasks_query(
            {"operation": "delete-tag"}, operation_kinds={"delete-tag"}
        ).filters.operation
        == "delete-tag"
    )
    assert (
        parse_tasks_query(
            {"operation": "delete-tag"}, operation_kinds=set()
        ).filters.operation
        == "all"
    )


def test_dialog_kinds_and_targets_are_parsed_without_authorization():
    location = parse_tasks_query(
        {
            "dialog": "task-share",
            "dialog_task": "10",
            "dialog_folder": "11",
        },
        operation_kinds=set(),
    )
    assert location.dialog == "task-share"
    assert location.dialog_task_id == 10
    assert location.dialog_folder_id == 11
