from marcedit_web.lib import external_task_migration as migration


def test_nonempty_subfield_edit_converts_to_guided_operation_with_provenance():
    line = "SUBFIELD_EDIT\t035\ta\tTFeba\t(SCTFEBA)\t0|0"

    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operation["kind"] == "guided-find-replace"
    assert item.operation["params"]["replacement_mode"] == "matched_text"
    assert item.instruction_sha256
    assert item.source_line == line


def test_empty_find_requires_one_explicit_choice_and_never_executes():
    line = "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0"

    item = migration.adapt_instruction(line)

    assert item.status == "choice_required"
    assert item.choices == migration.EMPTY_FIND_CHOICES
    assert item.operation is None


def test_selected_empty_find_choice_becomes_explicit_operation():
    item = migration.adapt_subfield_edit(
        "SUBFIELD_EDIT\t856\ty\t\tSmith link\t101|0",
        empty_find_choice="ensure_one",
    )
    assert item.status == "converted"
    assert item.operation["kind"] == "empty-find-subfield-policy"
    assert item.operation["params"]["policy"] == "ensure_one"


def test_unproven_external_syntax_remains_blocking():
    line = "SUBFIELD_EDIT\t856\tu\t^b\thttps://proxy/\t0|0"

    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert "not proven" in item.reason


def test_any_unproven_caret_prefixed_find_remains_blocking():
    line = "SUBFIELD_EDIT\t856\tu\t^bhttp://\thttps://proxy/\t0|0"

    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert "caret-prefixed" in item.reason


def test_review_preserves_source_order_and_unknown_lines():
    review = migration.build_review("DELETE\t001\nSUBFIELD_EDIT\t035\ta\tX\tY\n")
    items = review.items

    assert [item.source_line for item in items] == ["DELETE\t001", "SUBFIELD_EDIT\t035\ta\tX\tY"]
    assert items[0].status == "unresolved"
    assert items[1].status == "converted"
    assert len(review.blocking_items) == 1
    assert len(review.converted_operations) == 1
    assert "SUBFIELD_EDIT" in migration.ADAPTER_REGISTRY


def test_review_keeps_blocking_source_provenance_and_choices():
    review = migration.build_review(
        "SUBFIELD_EDIT\t856\tu\tfoo\tbar\n"
        "SUBFIELD_EDIT\t856\tu\t\tbar\n"
        "REPLACE\t(=856)\t=956\n"
    )
    assert [item.status for item in review.items] == [
        "converted", "choice_required", "unresolved"
    ]
    assert review.items[1].source_line.startswith("SUBFIELD_EDIT")
    assert len(review.items[1].instruction_sha256) == 64
    assert review.items[1].choices == migration.EMPTY_FIND_CHOICES


def test_proven_known_replace_and_sortby_signatures_convert():
    replace = migration.adapt_instruction(
        "REPLACE\t(=008.{25}).{1}(.+)\t$1o$2\t0\t0"
    )
    sort = migration.adapt_instruction("SORTBY\tALL\tTrue\tTrue")
    assert replace.status == "converted"
    assert replace.operation == {
        "kind": "set-008-form",
        "params": {"position": "23"},
    }
    assert sort.status == "converted"
    assert sort.operation["kind"] == "sort-fields"


def test_second_proven_replace_preserves_its_fixed_008_position():
    replace = migration.adapt_instruction(
        "REPLACE\t(=008.{31}).{1}(.+)\t$1o$2\t0\t0"
    )

    assert replace.operation == {
        "kind": "set-008-form",
        "params": {"position": "29"},
    }


def test_adapter_registry_is_the_dispatch_source(monkeypatch):
    sentinel = migration.MigrationItem(
        source_line="SORTBY\tALL",
        source_format="test",
        status="unresolved",
        reason="sentinel",
    )
    monkeypatch.setitem(
        migration.ADAPTER_REGISTRY,
        "SORTBY",
        lambda source_line: sentinel,
    )

    assert migration.adapt_instruction("SORTBY\tALL") is sentinel
