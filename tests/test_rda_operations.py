import pymarc

from marcedit_web.lib import rda_operations, task_builder


def _record(leader_type="a"):
    record = pymarc.Record()
    leader = "00000nam a2200000 a 4500"
    record.leader = pymarc.Leader(leader[:6] + leader_type + leader[7:])
    return record


def test_print_text_classification_uses_unmediated_volume():
    record = _record("a")

    result = rda_operations.apply_material_classification(record)

    assert result["material"] == "text_print"
    assert result["changed_fields"] == 3
    assert record.get("336").get_subfields("b") == ["txt"]
    assert record.get("337").get_subfields("b") == ["n"]
    assert record.get("338").get_subfields("b") == ["nc"]


def test_online_text_classification_requires_007_evidence():
    record = _record("a")
    record.add_field(pymarc.Field(tag="007", data="cr|||||||||||||"))

    result = rda_operations.apply_material_classification(record)

    assert result["material"] == "text_online"
    assert record.get("336").get_subfields("b") == ["txt"]
    assert record.get("337").get_subfields("b") == ["c"]
    assert record.get("338").get_subfields("b") == ["cr"]


def test_unsupported_carrier_evidence_fails_before_mutation():
    record = _record("a")
    record.add_field(pymarc.Field(tag="007", data="ha|||||||||||||"))

    try:
        rda_operations.apply_material_classification(record)
    except ValueError as exc:
        assert "ambiguous material classification" in str(exc)
    else:
        raise AssertionError("unsupported carrier evidence must fail loudly")

    assert record.get_fields("336", "337", "338") == []


def test_existing_rda_fields_are_preserved_by_default():
    record = _record("a")
    record.add_field(pymarc.Field(
        tag="336", indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "custom"), pymarc.Subfield("b", "x")],
    ))

    result = rda_operations.apply_material_classification(record)

    assert result["changed_fields"] == 2
    assert record.get("336").get_subfields("a") == ["custom"]


def test_ambiguous_leader_is_reported_without_mutation():
    record = _record("z")

    material, evidence = rda_operations.classify_material(record)

    assert material is None
    assert "no unambiguous" in evidence
    assert record.fields == []

    try:
        rda_operations.apply_material_classification(record)
    except ValueError as exc:
        assert "ambiguous material classification" in str(exc)
    else:
        raise AssertionError("ambiguous classification must fail loudly")


def test_explicit_rda_helpers_are_deterministic_and_idempotent():
    record = _record("a")
    record.add_field(pymarc.Field(
        tag="245", indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "Title"), pymarc.Subfield("h", "[electronic resource]")],
    ))
    record.add_field(pymarc.Field(
        tag="300", indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "100 p. : ill.")],
    ))

    assert rda_operations.mark_rda(record) is True
    assert rda_operations.mark_rda(record) is False
    assert rda_operations.remove_gmd(record, "[electronic resource]") == 1
    assert rda_operations.expand_abbreviations(record) == 1
    assert record.get("300").get_subfields("a") == ["100 pages : illustrations"]


def test_abbreviation_expansion_matches_complete_tokens_only():
    record = _record("a")
    record.add_field(pymarc.Field(
        tag="300", indicators=[" ", " "],
        subfields=[
            pymarc.Subfield("a", "pp. 12-15; chap. 2"),
            pymarc.Subfield("a", "1 p. : ill."),
        ],
    ))

    assert rda_operations.expand_abbreviations(record) == 1
    assert record.get("300").get_subfields("a") == [
        "pp. 12-15; chap. 2",
        "1 pages : illustrations",
    ]


def test_relator_codes_are_retained_and_terms_are_not_duplicated():
    record = _record("a")
    record.add_field(pymarc.Field(
        tag="100", indicators=["1", " "],
        subfields=[
            pymarc.Subfield("a", "Smith, Jane"),
            pymarc.Subfield("4", "aut"),
            pymarc.Subfield("e", "author"),
        ],
    ))

    assert rda_operations.normalize_relators(record) == 0
    assert record.get("100").get_subfields("4") == ["aut"]
    assert record.get("100").get_subfields("e") == ["author"]

    record.get("100").subfields = record.get("100").subfields[:-1]
    assert rda_operations.normalize_relators(record) == 1
    assert record.get("100").get_subfields("4") == ["aut"]
    assert record.get("100").get_subfields("e") == ["author"]


def test_promote_260_marks_264_as_publication():
    record = _record("a")
    record.add_field(pymarc.Field(
        tag="260", indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "Northampton")],
    ))

    assert rda_operations.promote_260(record) == 1
    assert list(record.get("264").indicators) == [" ", "1"]


def test_unknown_existing_field_action_fails_before_mutation():
    record = _record("a")

    try:
        rda_operations.apply_material_classification(
            record,
            existing_field_action="future-policy",
        )
    except ValueError as exc:
        assert "existing field action" in str(exc)
    else:
        raise AssertionError("unknown existing-field policy must fail loudly")

    assert record.get_fields("336", "337", "338") == []


def test_palette_and_compiler_expose_explicit_rda_operations():
    kinds = {entry["kind"] for entry in task_builder.OPERATIONS_PALETTE}
    expected = {
        "rda-classify-material", "rda-mark-rda", "rda-remove-gmd",
        "rda-expand-abbreviations", "rda-normalize-relators", "rda-promote-260",
    }
    assert expected <= kinds
    rendered = task_builder.render_ops_to_python([
        task_builder.Operation(kind="rda-mark-rda", params={}),
        task_builder.Operation(kind="rda-classify-material", params={}),
    ])
    assert "mark_rda(record)" in rendered["body"]
    assert "apply_material_classification" in rendered["body"]


def test_smith_profile_expands_to_editable_explicit_operations():
    profile = rda_operations.smith_profile_operations()
    assert [item["kind"] for item in profile] == [
        "rda-classify-material",
        "rda-mark-rda",
        "rda-remove-gmd",
        "rda-expand-abbreviations",
        "rda-normalize-relators",
        "rda-promote-260",
    ]
    profile[0]["params"]["mode"] = "fixed"
    assert rda_operations.SMITH_RDA_PROFILE[0]["params"]["mode"] == "classify"
