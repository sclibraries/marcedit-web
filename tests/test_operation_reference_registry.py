import pytest
from pathlib import Path
from pymarc import MARCReader

from marcedit_web.lib import operation_reference, task_builder


QUICK_FIXTURE = Path(__file__).parent / "fixtures" / "quick-field-changes" / "multiple-070-and-856.mrc"


def test_reference_registry_matches_supported_palette_exactly():
    assert set(operation_reference.REFERENCE_REGISTRY) == {
        entry["kind"] for entry in task_builder.OPERATIONS_PALETTE
    }


def test_every_reference_entry_has_required_sections_and_example():
    required = {
        "purpose", "when_to_use", "inputs", "behavior", "preserves",
        "skip_behavior", "error_behavior", "example", "stored_representation",
        "related",
    }
    for kind, entry in operation_reference.REFERENCE_REGISTRY.items():
        assert required <= set(entry), kind
        assert entry["example"]["before"]
        assert entry["example"]["after"]
        assert set(entry["inputs"]) == {
            param["name"]
            for palette in task_builder.OPERATIONS_PALETTE
            if palette["kind"] == kind
            for param in palette["params"]
        }


def test_generated_operation_reference_is_fresh():
    if not operation_reference.GUIDE_PATH.exists():
        pytest.skip(
            "generated operation reference is unavailable in the Docker "
            "image; mount the repository read-only for the authoritative check"
        )
    expected = operation_reference.render_markdown()
    checked_in = operation_reference.GUIDE_PATH.read_text(encoding="utf-8")
    assert checked_in == expected


def test_reference_search_includes_behavior_and_examples():
    entries = operation_reference.search_entries("surrounding")
    assert any(entry["kind"] == "guided-find-replace" for entry in entries)


def test_quick_change_reference_is_separate_from_task_palette_registry():
    expected_labels = [
        "Add field",
        "Add subfield",
        "Copy field",
        "Delete field",
        "Delete subfield",
        "Move or retag field",
        "Remove exact duplicate fields",
        "Set indicators",
        "Swap field occurrences",
    ]
    quick = operation_reference.QUICK_CHANGE_REFERENCE

    assert [entry["label"] for entry in operation_reference.search_quick_entries()] == expected_labels
    assert set(quick) == {
        "add-field",
        "add-subfield",
        "copy-field",
        "delete-field",
        "delete-subfield",
        "move-field",
        "remove-duplicate-fields",
        "set-indicators",
        "swap-field-occurrences",
    }
    assert set(quick) - set(operation_reference.REFERENCE_REGISTRY)
    assert set(operation_reference.REFERENCE_REGISTRY) == {
        entry["kind"] for entry in task_builder.OPERATIONS_PALETTE
    }


def test_quick_change_reference_search_and_markdown_cover_cataloger_contract():
    entries = operation_reference.search_entries("quick")
    assert {entry["label"] for entry in entries} >= {
        "Add field",
        "Add subfield",
        "Copy field",
        "Delete field",
        "Delete subfield",
        "Move or retag field",
        "Remove exact duplicate fields",
        "Set indicators",
        "Swap field occurrences",
    }

    markdown = operation_reference.render_markdown()
    for phrase in (
        "one-operation",
        "filtered before",
        "First, Last, Numbered, or Every",
        "skipped and grouped by reason",
        "optional Advanced regular expression",
        "complete selected field objects",
        "complete field identity",
        "recoverable",
        "two distinguishable 070 fields",
        "several 856 fields",
        "Reorder fields",
    ):
        assert phrase.casefold() in markdown.casefold(), phrase

    quick_markdown = markdown.split("## Common field changes", 1)[1]
    assert "Python" not in quick_markdown
    assert "fingerprint" not in quick_markdown.casefold()


def test_quick_change_browser_fixture_is_small_and_sanitized():
    records = list(MARCReader(QUICK_FIXTURE.read_bytes(), to_unicode=True))
    assert len(records) == 3
    assert {record["001"].value() for record in records} == {
        "quick-070-856-1",
        "quick-070-856-2",
        "quick-missing-occurrences",
    }
    assert len(records[0].get_fields("070")) == 2
    assert len(records[0].get_fields("856")) == 3
    assert len(records[0].get_fields("035")) == 3
    first, second, near = records[0].get_fields("035")
    assert str(first) == str(second)
    assert str(second) != str(near)
    assert all(record.get_fields("008") for record in records)
    assert len(records[1].get_fields("070")) == 1
    assert not records[2].get_fields("070")
