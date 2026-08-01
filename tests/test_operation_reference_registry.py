from marcedit_web.lib import operation_reference, task_builder


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
    expected = operation_reference.render_markdown()
    checked_in = operation_reference.GUIDE_PATH.read_text(encoding="utf-8")
    assert checked_in == expected


def test_reference_search_includes_behavior_and_examples():
    entries = operation_reference.search_entries("surrounding")
    assert any(entry["kind"] == "guided-find-replace" for entry in entries)
