import json
from pathlib import Path
import textwrap

import pymarc
import pytest

from marcedit_web.lib import external_task_migration as migration
from marcedit_web.lib import task_builder
from marcedit_web.lib.external_task_parser import (
    instruction_shape,
    parse_instruction,
)


COMPATIBILITY_MANIFEST = (
    Path(__file__).parents[1]
    / "marcedit_web"
    / "schemas"
    / "external-task-compatibility-v1.json"
)
PARSER_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "external_task_migration"
    / "parser-shapes.tasksfile.txt"
)
CORE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "external_task_migration"
    / "core-automatic.tasksfile.txt"
)
SUBFIELD_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "external_task_migration"
    / "subfield-operations.tasksfile.txt"
)
TASK_5_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "external_task_migration"
    / "field-predicate-operations.tasksfile.txt"
)


def _compatibility_manifest():
    return json.loads(COMPATIBILITY_MANIFEST.read_text())


def _exercised_fixtures():
    exercised = {}
    fixture_id = None
    for fixture in (PARSER_FIXTURE, CORE_FIXTURE, SUBFIELD_FIXTURE, TASK_5_FIXTURE):
        for line in fixture.read_text().splitlines():
            if line.startswith("# FIXTURE_ID: "):
                fixture_id = line.removeprefix("# FIXTURE_ID: ")
                continue
            assert fixture_id is not None, (
                "every fixture line requires an explicit ID"
            )
            exercised[fixture_id] = parse_instruction(line)
            fixture_id = None
    assert fixture_id is None, "every fixture ID requires an instruction line"
    return exercised


def _run_operations(item, record):
    rendered = task_builder.render_ops_to_python([
        task_builder.Operation.from_dict(operation)
        for operation in item.operations
    ])
    source = "\n".join([
        *rendered["imports"],
        "",
        "def apply(record):",
        textwrap.indent(rendered["body"], "    "),
    ])
    namespace = {}
    exec(source, namespace)
    namespace["apply"](record)


def _field_list(record):
    return [
        (field.tag, field.data)
        if field.is_control_field()
        else (
            field.tag,
            tuple(field.indicators),
            tuple((subfield.code, subfield.value) for subfield in field.subfields),
        )
        for field in record.fields
    ]


@pytest.mark.parametrize(
    ("line", "policy"),
    [
        ("ADD\t506\t1\\$aAccess.$5ABC\t100\t", "append"),
        ("ADD\t050\t\\\\$aOnline\t101\t", "skip_if_tag_exists"),
        (
            "ADD\t336\t\\\\$atext$btxt$2rdacontent\t108\t",
            "skip_if_identical",
        ),
    ],
)
def test_add_codes_become_named_policies(line, policy):
    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operations[0]["params"]["existing_field_action"] == policy


def test_add_ignores_only_parser_approved_empty_surplus_columns():
    item = migration.adapt_instruction(
        "ADD\t506\t1\\$aAccess.$5ABC\t100\t\t"
    )

    assert item.status == "converted"
    assert item.operations[0]["params"]["existing_field_action"] == "append"


@pytest.mark.parametrize(
    ("external", "condition"),
    [
        ("//=LDR.{8}[amt][m].+//", "books"),
        ("/=LDR.{9}s.+/", "serials"),
        ("///=LDR.{9}i.+///", "databases"),
        ("=LDR.{8}[e,f].+", "maps"),
        ("/=LDR.{8}g.+/", "videos"),
        ("/=LDR.{8}[i,j].+/", "audios"),
        ("/=LDR.{8}[c,d].+/", "scores"),
        ("/=LDR.{8}k.+/", "images"),
    ],
)
def test_add_106_accepts_each_reviewed_leader_condition(external, condition):
    item = migration.adapt_instruction(
        "ADD\t655\t\\7$aElectronic resource$2local\t106\t" + external
    )

    assert item.status == "converted"
    assert item.operations[0]["params"]["condition"] == condition


@pytest.mark.parametrize("tag", ["001", "9XX"])
def test_delete_exact_and_wildcard_tags_convert(tag):
    item = migration.adapt_instruction(
        f"DELETE\t{tag}\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )

    assert item.status == "converted"
    assert item.operations == ({"kind": "delete-tag", "params": {"tag": tag}},)


def test_filtered_copy_and_plain_matched_delete_emit_predicate_operations():
    copied = migration.adapt_instruction(
        "COPY\t856\t857\tfalse\t$3JSTOR\t\tfalse\t"
    )
    deleted = migration.adapt_instruction(
        "DELETE\t655\tElectronic books\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )

    assert copied.status == "converted"
    assert copied.operations == ({
        "kind": "copy-field",
        "params": {
            "src_tag": "856",
            "dst_tag": "857",
            "predicate": {"subfield_matches": [{
                "code": "3", "mode": "contains", "value": "JSTOR",
                "ignore_case": False,
            }]},
        },
    },)
    assert deleted.status == "converted"
    assert deleted.operations[0]["kind"] == "delete-by-subfield"
    assert deleted.operations[0]["params"] == {
        "tag": "655", "match": "Electronic books",
    }


def test_cross_type_unfiltered_copy_blocks_instead_of_losing_control_value():
    item = migration.adapt_instruction(
        "COPY\t001\t035\tfalse\t\t\tfalse\t"
    )

    assert item.status == "unresolved"
    assert item.operations == ()
    assert item.recommended_operation == "copy-field"
    assert "control" in item.reason
    assert item.cataloger_action


def test_plain_matched_delete_preserves_any_subfield_scope():
    record = pymarc.Record()
    selected = pymarc.Field(
        tag="655", indicators=[" ", "7"],
        subfields=[pymarc.Subfield("x", "Electronic books")],
    )
    retained = pymarc.Field(
        tag="655", indicators=[" ", "7"],
        subfields=[pymarc.Subfield("a", "Streaming video")],
    )
    record.add_field(selected, retained)

    item = migration.adapt_instruction(
        "DELETE\t655\tElectronic books\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )
    _run_operations(item, record)

    assert item.operations == ({
        "kind": "delete-by-subfield",
        "params": {"tag": "655", "match": "Electronic books"},
    },)
    assert record.get_fields("655") == [retained]


@pytest.mark.parametrize(
    "line",
    [
        "COPY\t856\t857\ttrue\t$3JSTOR\t\tfalse\t",
        "COPY\t856\t857\tfalse\t$3JSTOR\tchanged\tfalse\t",
        "DELETE\t650\t\\6$a\t0\tTrue\tFalse\tFalse\tFalse\tFalse",
        "DELETE\t035\t9\\$a(ABC)\t0\tFalse\tFalse\tFalse\tFalse\tFalse",
    ],
)
def test_changed_filter_flags_and_mnemonic_near_misses_block_safely(line):
    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert item.operations == ()
    assert item.recommended_operation in {"copy-field", "delete-by-subfield"}
    assert isinstance(item.prefilled_params, dict)
    assert item.cataloger_action


@pytest.mark.parametrize(
    ("line", "predicate"),
    [
        (
            "DELETE\t650\t\\6$a\t0\tFalse\tFalse\tFalse\tFalse\tFalse",
            {
                "ind1": " ", "ind2": "6",
                "subfield_matches": [{
                    "code": "a", "mode": "exists", "value": "*",
                    "ignore_case": False,
                }],
            },
        ),
        (
            "DELETE\t035\t9\\$a(ABC)\t0\tTrue\tFalse\tFalse\tFalse\tFalse",
            {
                "ind1": "9", "ind2": " ",
                "subfield_matches": [{
                    "code": "a", "mode": "regex", "value": "(ABC)",
                    "ignore_case": False,
                }],
            },
        ),
    ],
)
def test_proven_mnemonic_delete_filters_convert_structurally(line, predicate):
    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operations == ({
        "kind": "delete-by-subfield",
        "params": {"tag": line.split("\t")[1], "predicate": predicate},
    },)


def test_mnemonic_delete_removes_only_the_complete_selected_signature():
    record = pymarc.Record()
    selected = pymarc.Field(
        tag="650", indicators=[" ", "6"],
        subfields=[pymarc.Subfield("a", "Topic")],
    )
    wrong_indicator = pymarc.Field(
        tag="650", indicators=[" ", "7"],
        subfields=[pymarc.Subfield("a", "Topic")],
    )
    missing_subfield = pymarc.Field(
        tag="650", indicators=[" ", "6"],
        subfields=[pymarc.Subfield("x", "Topic")],
    )
    record.add_field(selected, wrong_indicator, missing_subfield)

    item = migration.adapt_instruction(
        "DELETE\t650\t\\6$a\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )
    _run_operations(item, record)

    assert record.get_fields("650") == [wrong_indicator, missing_subfield]


@pytest.mark.parametrize(
    ("flags", "policy"),
    [
        ((False, False, True, False), "skip_if_tag_exists"),
        ((False, False, False, True), "append"),
    ],
)
def test_build_field_corpus_flags_become_named_policies(flags, policy):
    rendered_flags = "\t".join(str(flag) for flag in flags)
    item = migration.adapt_instruction(
        "buildnewfield\t=035  9\\$a({003}){001}\t" + rendered_flags
    )

    assert item.status == "converted"
    params = item.operations[0]["params"]
    assert params["existing_field_action"] == policy
    assert params["missing_control_action"] == "skip_field"


def test_sortby_all_true_true_is_the_only_automatic_sort_shape():
    item = migration.adapt_instruction("SORTBY\tALL\tTrue\tTrue")

    assert item.status == "converted"
    assert item.operations == ({"kind": "sort-fields", "params": {}},)


@pytest.mark.parametrize(
    ("line", "recommended_operation"),
    [
        (
            "DELETE\t506\t\t0\tTrue\tFalse\tFalse\tFalse\tFalse",
            "delete-tag",
        ),
        ("ADD\t655\t\\7$aValue\t106\t/=LDR.*/", "add-field"),
        ("ADD\t001\t\\\\$aValue\t100\t", "add-field"),
        (
            "buildnewfield\t=035  9\\$a{001}\tFalse\tTrue\tFalse\tFalse",
            "build-field",
        ),
        (
            "buildnewfield\t=001  \\\\$aValue\tFalse\tFalse\tFalse\tTrue",
            "build-field",
        ),
        (
            "RDAHELPER\t1|1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|"
            "language of cataloging|0",
            "rda-classify-material",
        ),
        ("SORTBY\tALL\tTrue\tFalse", "sort-fields"),
    ],
)
def test_core_near_misses_decline_with_structured_actionable_suggestion(
    line, recommended_operation
):
    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert item.intent
    assert item.reason
    assert item.recommended_operation == recommended_operation
    assert isinstance(item.prefilled_params, dict)
    assert item.cataloger_action


@pytest.mark.parametrize(
    ("position", "cataloger_label"),
    [
        (1, "Add MARC 336 Content Type"),
        (2, "Add MARC 337 Media Type and 338 Carrier Type"),
        (3, "Add MARC 344 Sound Characteristics"),
        (4, "Add MARC 345 Projection Characteristics"),
        (5, "Add MARC 346 Video Characteristics"),
        (6, "Add MARC 347 Digital File Characteristics"),
        (7, "Add MARC 380 Form of Work"),
        (8, "Add MARC 381 Other Distinguishing Characteristics"),
        (9, "Evaluate MARC 260/264 publication fields"),
        (10, "Always use copyright and phonogram symbols"),
        (11, "Add qualifying information to MARC 015/020/024/027"),
        (12, "Modify MARC 040 to add $e rda"),
        (13, "Process MARC 502 dissertation notes"),
        (14, "Delete the General Material Designation from MARC 245 $h"),
        (15, "Generate a General Material Designation"),
        (16, "Expand RDA abbreviations"),
        (18, "Add a relator term in MARC 100 $e"),
    ],
)
def test_rda_near_miss_names_each_enabled_option_for_catalogers(
    position, cataloger_label
):
    positions = ["0"] * 18
    positions[16] = "language of cataloging"
    positions[position - 1] = "1"

    item = migration.adapt_instruction(
        "RDAHELPER\t" + "|".join(positions)
    )

    assert item.status == "unresolved"
    assert cataloger_label in item.reason
    assert "position" not in item.reason.casefold()


def test_rda_near_miss_names_enabled_options_and_language_setting():
    item = migration.adapt_instruction(
        "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|eng|0"
    )

    assert "Add MARC 336 Content Type" in item.reason
    assert "Add MARC 337 Media Type and 338 Carrier Type" in item.reason
    assert "Cataloging language setting: eng" in item.reason
    assert "position" not in item.reason.casefold()


def test_malformed_rda_switch_names_option_and_other_enabled_intent():
    positions = ["0"] * 18
    positions[2] = "maybe"
    positions[11] = "1"
    positions[16] = "language of cataloging"

    item = migration.adapt_instruction(
        "RDAHELPER\t" + "|".join(positions)
    )

    assert "Add MARC 344 Sound Characteristics" in item.reason
    assert "Modify MARC 040 to add $e rda" in item.reason
    assert "position" not in item.reason.casefold()


@pytest.mark.parametrize(
    ("enabled_position", "cataloger_label"),
    [
        (1, "Add MARC 336 Content Type"),
        (12, "Modify MARC 040 to add $e rda"),
    ],
)
def test_short_rda_near_miss_preserves_recognizable_enabled_intent(
    enabled_position, cataloger_label
):
    positions = ["0"] * 16
    positions[enabled_position - 1] = "1"
    positions.append("language of cataloging")

    item = migration.adapt_instruction(
        "RDAHELPER\t" + "|".join(positions)
    )

    assert item.status == "unresolved"
    assert "17 serialized values; expected 18" in item.reason
    assert cataloger_label in item.reason
    assert "1 serialized value is missing" in item.reason
    assert "position" not in item.reason.casefold()


def test_short_rda_near_miss_stops_before_malformed_prefix_value():
    positions = ["0"] * 16
    positions[2] = ""
    positions[11] = "1"
    positions.append("language of cataloging")

    item = migration.adapt_instruction(
        "RDAHELPER\t" + "|".join(positions)
    )

    assert "17 serialized values; expected 18" in item.reason
    assert "Add MARC 344 Sound Characteristics" in item.reason
    assert "Modify MARC 040 to add $e rda" not in item.reason
    assert "position" not in item.reason.casefold()


def test_long_rda_near_miss_does_not_guess_extra_value_as_known_intent():
    positions = ["0"] * 18
    positions[0] = "1"
    positions[16] = "language of cataloging"
    positions.append("1")

    item = migration.adapt_instruction(
        "RDAHELPER\t" + "|".join(positions)
    )

    assert "19 serialized values; expected 18" in item.reason
    assert "Add MARC 336 Content Type" in item.reason
    assert "1 unrecognized extra serialized value" in item.reason
    assert "Add a relator term in MARC 100 $e" not in item.reason
    assert "position" not in item.reason.casefold()


def test_unknown_numeric_option_is_not_normalized_to_supported_add_policy():
    item = migration.adapt_instruction("ADD\t506\t1\\$aAccess\t107\t")

    assert item.status == "unresolved"
    assert item.recommended_operation == "add-field"
    assert item.prefilled_params["tag"] == "506"
    assert "107" in item.reason


def test_corpus_rda_signature_expands_to_visible_open_equivalent():
    item = migration.adapt_instruction(
        "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0"
    )

    assert [op["kind"] for op in item.operations] == ["rda-classify-material"]
    assert item.disclosure == (
        "Smith open equivalent; not a byte-for-byte external emulation"
    )


def test_compiled_rda_replacement_fails_before_mutating_ambiguous_record():
    item = migration.adapt_instruction(
        "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|"
        "language of cataloging|0"
    )
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nzm a2200000 a 4500")
    before = _field_list(record)

    with pytest.raises(ValueError, match="ambiguous material classification"):
        _run_operations(item, record)

    assert _field_list(record) == before


def test_singular_operation_accessor_remains_read_only_compatibility_surface():
    item = migration.adapt_instruction("SORTBY\tALL\tTrue\tTrue")

    assert item.operation is item.operations[0]
    with pytest.raises(AttributeError):
        item.operation = {"kind": "delete-tag", "params": {"tag": "001"}}


def test_review_flattens_ordered_operation_expansions_without_singular_guess():
    expanded = migration.MigrationItem(
        source_line="source",
        source_format="test",
        status="converted",
        operations=(
            {"kind": "delete-tag", "params": {"tag": "001"}},
            {"kind": "sort-fields", "params": {}},
        ),
    )
    review = migration.MigrationReview(items=(expanded,))

    assert expanded.operation is None
    assert review.converted_operations == expanded.operations


def test_converted_core_operations_preserve_complete_field_effects():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag="001", data="id-1"))
    record.add_field(pymarc.Field(tag="003", data="ABC"))
    record.add_field(pymarc.Field(
        tag="506",
        indicators=["1", " "],
        subfields=[pymarc.Subfield("a", "Existing")],
    ))
    record.add_field(pymarc.Field(
        tag="336",
        indicators=[" ", " "],
        subfields=[
            pymarc.Subfield("a", "text"),
            pymarc.Subfield("b", "txt"),
            pymarc.Subfield("2", "rdacontent"),
        ],
    ))

    for line in (
        "ADD\t506\t1\\$aAccess$5ABC\t100\t",
        "ADD\t336\t\\\\$atext$btxt$2rdacontent\t108\t",
        "buildnewfield\t=035  9\\$a({003}){001}\tFalse\tFalse\tFalse\tTrue",
    ):
        _run_operations(migration.adapt_instruction(line), record)

    assert _field_list(record) == [
        ("001", "id-1"),
        ("003", "ABC"),
        ("035", ("9", " "), (("a", "(ABC)id-1"),)),
        ("506", ("1", " "), (("a", "Existing"),)),
        ("336", (" ", " "), (("a", "text"), ("b", "txt"), ("2", "rdacontent"))),
        ("506", ("1", " "), (("a", "Access"), ("5", "ABC"))),
    ]


def test_build_missing_source_and_existing_tag_policies_do_not_mutate_fields():
    missing_source = pymarc.Record()
    missing_source.add_field(pymarc.Field(tag="003", data="ABC"))
    build_always = migration.adapt_instruction(
        "buildnewfield\t=035  9\\$a({003}){001}\tFalse\tFalse\tFalse\tTrue"
    )
    _run_operations(build_always, missing_source)
    assert _field_list(missing_source) == [("003", "ABC")]

    existing_tag = pymarc.Record()
    existing_tag.add_field(pymarc.Field(tag="001", data="id-1"))
    existing_tag.add_field(pymarc.Field(tag="003", data="ABC"))
    existing_tag.add_field(pymarc.Field(
        tag="035", indicators=[" ", " "], subfields=[pymarc.Subfield("a", "keep")]
    ))
    build_if_absent = migration.adapt_instruction(
        "buildnewfield\t=035  9\\$a({003}){001}\tFalse\tFalse\tTrue\tFalse"
    )
    before = _field_list(existing_tag)
    _run_operations(build_if_absent, existing_tag)
    assert _field_list(existing_tag) == before


def test_leader_condition_adds_only_to_matching_records():
    item = migration.adapt_instruction(
        "ADD\t655\t\\7$aElectronic books$2local\t106\t/=LDR.{8}[amt][m].+/"
    )
    matching = pymarc.Record()
    matching.leader = pymarc.Leader("00000nam a2200000 a 4500")
    nonmatching = pymarc.Record()
    nonmatching.leader = pymarc.Leader("00000ngm a2200000 a 4500")

    _run_operations(item, matching)
    _run_operations(item, nonmatching)

    assert _field_list(matching) == [
        ("655", (" ", "7"), (("a", "Electronic books"), ("2", "local")))
    ]
    assert _field_list(nonmatching) == []


def test_reviewed_image_leader_condition_compiles_and_selects_type_k():
    item = migration.adapt_instruction(
        "ADD\t655\t\\7$aElectronic images$2local\t106\t/=LDR.{8}k.+/"
    )
    matching = pymarc.Record()
    matching.leader = pymarc.Leader("00000nkm a2200000 a 4500")
    nonmatching = pymarc.Record()
    nonmatching.leader = pymarc.Leader("00000nam a2200000 a 4500")

    _run_operations(item, matching)
    _run_operations(item, nonmatching)

    assert [field.tag for field in matching.fields] == ["655"]
    assert _field_list(nonmatching) == []


def test_delete_and_sort_effects_compare_complete_field_lists():
    record = pymarc.Record()
    record.add_field(pymarc.Field(
        tag="999",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "drop")],
    ))
    record.add_field(pymarc.Field(
        tag="245",
        indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "Title")],
    ))
    record.add_field(pymarc.Field(
        tag="901",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "drop too")],
    ))
    record.add_field(pymarc.Field(
        tag="100",
        indicators=["1", " "],
        subfields=[pymarc.Subfield("a", "Name")],
    ))

    delete = migration.adapt_instruction(
        "DELETE\t9XX\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )
    _run_operations(delete, record)
    _run_operations(migration.adapt_instruction("SORTBY\tALL\tTrue\tTrue"), record)

    assert _field_list(record) == [
        ("100", ("1", " "), (("a", "Name"),)),
        ("245", ("1", "0"), (("a", "Title"),)),
    ]


@pytest.mark.parametrize(
    ("find", "replacement", "mode"),
    [
        ("Old", "New", "matched_text"),
        ("^b", "https://proxy/", "prepend"),
        ("^e", "eb", "append"),
    ],
)
def test_subfield_special_forms_convert(find, replacement, mode):
    line = f"SUBFIELD_EDIT\t856\tu\t{find}\t{replacement}\t0|0"

    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operations[0]["params"]["replacement_mode"] == mode
    assert item.instruction_sha256
    assert item.source_line == line


def test_literal_subfield_edit_preserves_matched_text_parameters():
    line = "SUBFIELD_EDIT\t035\ta\tTFeba\t(SCTFEBA)\t0|0"

    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operation["kind"] == "guided-find-replace"
    assert item.operation["params"]["replacement_mode"] == "matched_text"
    assert item.instruction_sha256
    assert item.source_line == line


def test_empty_find_101_adds_only_when_missing():
    line = "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0"

    item = migration.adapt_instruction(line)

    assert item.status == "converted"
    assert item.operations == ({
        "kind": "empty-find-subfield-policy",
        "params": {
            "tag": "856",
            "code": "y",
            "value": "Smith: Link to resource",
            "policy": "add_if_missing",
        },
    },)


@pytest.mark.parametrize(
    "line",
    [
        "SUBFIELD_EDIT\t856\tu\tOld\tNew\t0|0\t",
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0\t",
    ],
)
def test_subfield_adapters_accept_parser_approved_empty_surplus(line):
    item = migration.adapt_instruction(line)

    assert item.status == "converted"


def test_selected_empty_find_choice_becomes_explicit_operation():
    item = migration.adapt_subfield_edit(
        "SUBFIELD_EDIT\t856\ty\t\tSmith link\t101|0",
        empty_find_choice="ensure_one",
    )
    assert item.status == "converted"
    assert item.operation["kind"] == "empty-find-subfield-policy"
    assert item.operation["params"]["policy"] == "ensure_one"


@pytest.mark.parametrize(
    ("line", "recommended_operation"),
    [
        ("SUBFIELD_EDIT\t856\tu\t^c\tz\t0|0", "guided-find-replace"),
        (
            "SUBFIELD_EDIT\t856\tu\t^bhttp://\thttps://proxy/\t0|0",
            "guided-find-replace",
        ),
        (
            "SUBFIELD_EDIT\t260\tc\t\t008|7|. ?u|\t0|0",
            "guided-find-replace",
        ),
        (
            "SUBFIELD_EDIT\t856\ty\tOld\tNew\t101|0",
            "guided-find-replace",
        ),
        (
            "SUBFIELD_EDIT\t856\ty\t\tNew\t999|0",
            "empty-find-subfield-policy",
        ),
        (
            "SUBFIELD_EDIT\t85X\tu\tOld\tNew\t0|0",
            "guided-find-replace",
        ),
        (
            "SUBFIELD_EDIT\t856\tupper\tOld\tNew\t0|0",
            "guided-find-replace",
        ),
        (
            "SUBFIELD_EDIT\t856\tu\tOld\tNew",
            "guided-find-replace",
        ),
    ],
)
def test_subfield_edit_near_misses_are_actionable_blockers(
    line, recommended_operation
):
    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert item.intent
    assert item.reason
    assert item.recommended_operation == recommended_operation
    assert isinstance(item.prefilled_params, dict)
    assert item.cataloger_action


def test_pipe_move_blocker_explains_why_it_cannot_convert():
    item = migration.adapt_instruction(
        "SUBFIELD_EDIT\t260\tc\t\t008|7|. ?u|\t0|0"
    )

    assert "pipe-move" in item.reason
    assert item.prefilled_params == {
        "target_kind": "subfield",
        "tag": "260",
        "subfield": "c",
    }


def test_subfield_remove_107_converts_to_exact_value_deletion():
    item = migration.adapt_instruction(
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0"
    )

    assert item.status == "converted"
    assert item.operations == ({
        "kind": "delete-subfield-if-value",
        "params": {
            "tag": "035",
            "code": "z",
            "value": "(OCoLC)",
            "match": "exact",
            "trim": False,
            "ignore_case": False,
        },
    },)


@pytest.mark.parametrize(
    "line",
    [
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t108|0",
        "SUBFIELD_REMOVE\t03X\tz\t(OCoLC)\t107|0",
        "SUBFIELD_REMOVE\t035\tupper\t(OCoLC)\t107|0",
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)",
    ],
)
def test_subfield_remove_near_misses_are_actionable_blockers(line):
    item = migration.adapt_instruction(line)

    assert item.status == "unresolved"
    assert item.intent
    assert item.reason
    assert item.recommended_operation == "delete-subfield-if-value"
    assert isinstance(item.prefilled_params, dict)
    assert item.cataloger_action


@pytest.mark.parametrize("mode", ["prepend", "append"])
def test_subfield_special_forms_change_selected_values_without_creating_source(
    mode,
):
    record = pymarc.Record()
    record.add_field(pymarc.Field(
        tag="856",
        indicators=["4", "0"],
        subfields=[pymarc.Subfield("u", "one"), pymarc.Subfield("y", "First")],
    ))
    record.add_field(pymarc.Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[pymarc.Subfield("u", "two")],
    ))
    record.add_field(pymarc.Field(
        tag="856",
        indicators=["4", "0"],
        subfields=[pymarc.Subfield("y", "No URL")],
    ))
    marker = "prefix:" if mode == "prepend" else ":suffix"
    find = "^b" if mode == "prepend" else "^e"

    _run_operations(
        migration.adapt_instruction(
            f"SUBFIELD_EDIT\t856\tu\t{find}\t{marker}\t0|0"
        ),
        record,
    )

    expected = (
        ["prefix:one", "prefix:two"]
        if mode == "prepend"
        else ["one:suffix", "two:suffix"]
    )
    assert [
        value
        for field in record.get_fields("856")
        for value in field.get_subfields("u")
    ] == expected
    assert record.get_fields("856")[2].get_subfields("u") == []


def test_empty_find_101_adds_once_only_to_fields_missing_the_subfield():
    record = pymarc.Record()
    record.add_field(pymarc.Field(
        tag="856",
        indicators=["4", "0"],
        subfields=[pymarc.Subfield("u", "one"), pymarc.Subfield("y", "Existing")],
    ))
    record.add_field(pymarc.Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[pymarc.Subfield("u", "two")],
    ))

    _run_operations(
        migration.adapt_instruction(
            "SUBFIELD_EDIT\t856\ty\t\tLink to resource\t101|0"
        ),
        record,
    )

    assert [
        field.get_subfields("y") for field in record.get_fields("856")
    ] == [["Existing"], ["Link to resource"]]


def test_subfield_remove_preserves_fields_nonmatches_and_other_subfields():
    record = pymarc.Record()
    record.add_field(pymarc.Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[
            pymarc.Subfield("a", "keep-a"),
            pymarc.Subfield("z", "(OCoLC)"),
            pymarc.Subfield("z", "keep-z"),
            pymarc.Subfield("z", "(OCoLC)"),
            pymarc.Subfield("z", " (OCoLC) "),
        ],
    ))
    record.add_field(pymarc.Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[
            pymarc.Subfield("a", "second"),
            pymarc.Subfield("z", "not a match"),
        ],
    ))

    _run_operations(
        migration.adapt_instruction(
            "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0"
        ),
        record,
    )

    assert _field_list(record) == [
        (
            "035",
            (" ", " "),
            (("a", "keep-a"), ("z", "keep-z"), ("z", " (OCoLC) ")),
        ),
        (
            "035",
            (" ", " "),
            (("a", "second"), ("z", "not a match")),
        ),
    ]


def test_review_preserves_source_order_and_unknown_lines():
    review = migration.build_review(
        "DELETE\t001\nSUBFIELD_EDIT\t035\ta\tX\tY\t0|0\n"
    )
    items = review.items

    assert [item.source_line for item in items] == [
        "DELETE\t001",
        "SUBFIELD_EDIT\t035\ta\tX\tY\t0|0",
    ]
    assert items[0].status == "unresolved"
    assert items[1].status == "converted"
    assert len(review.blocking_items) == 1
    assert len(review.converted_operations) == 1
    assert "SUBFIELD_EDIT" in migration.ADAPTER_REGISTRY


def test_review_keeps_blocking_source_provenance_and_suggestions():
    review = migration.build_review(
        "SUBFIELD_EDIT\t856\tu\tfoo\tbar\t0|0\n"
        "SUBFIELD_EDIT\t856\tu\t\tbar\t0|0\n"
        "REPLACE\t(=856)\t=956\n"
    )
    assert [item.status for item in review.items] == [
        "converted", "unresolved", "unresolved"
    ]
    assert review.items[1].source_line.startswith("SUBFIELD_EDIT")
    assert len(review.items[1].instruction_sha256) == 64
    assert review.items[1].recommended_operation == (
        "empty-find-subfield-policy"
    )
    assert review.items[1].cataloger_action


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


def test_compatibility_manifest_lists_only_registered_exercised_adapters():
    migration.validate_compatibility_manifest(
        _compatibility_manifest(),
        exercised_fixtures=_exercised_fixtures(),
    )


def test_compatibility_manifest_rejects_fixture_that_shapes_but_does_not_convert():
    exercised = _exercised_fixtures()
    invalid_delete = parse_instruction(
        "DELETE\tABC\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse"
    )
    assert instruction_shape(invalid_delete) == "delete-exact"
    exercised["delete-exact"] = invalid_delete

    with pytest.raises(
        migration.CompatibilityContractError,
        match="delete-v1 fixture delete-exact did not convert",
    ):
        migration.validate_compatibility_manifest(
            _compatibility_manifest(),
            exercised_fixtures=exercised,
        )


def test_compatibility_manifest_rejects_unknown_schema_version():
    manifest = _compatibility_manifest()
    manifest["schema_version"] = 2

    with pytest.raises(migration.CompatibilityContractError, match="schema"):
        migration.validate_compatibility_manifest(
            manifest,
            exercised_fixtures=_exercised_fixtures(),
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("adapter_id", "drifted-adapter"),
        ("verbs", []),
        ("verbs", ["REPLACE"]),
        ("shape_ids", []),
        ("shape_ids", ["drifted-shape"]),
        ("fixture_ids", []),
        ("fixture_ids", ["drifted-fixture"]),
    ],
)
def test_compatibility_manifest_rejects_empty_or_drifted_fields(
    field, replacement
):
    manifest = _compatibility_manifest()
    manifest["adapters"][0][field] = replacement

    with pytest.raises(migration.CompatibilityContractError):
        migration.validate_compatibility_manifest(
            manifest,
            exercised_fixtures=_exercised_fixtures(),
        )


@pytest.mark.parametrize("adapters", [[], [{"adapter_id": "extra"}]])
def test_compatibility_manifest_rejects_removed_or_extra_adapter_rows(adapters):
    manifest = _compatibility_manifest()
    manifest["adapters"] = adapters

    with pytest.raises(migration.CompatibilityContractError):
        migration.validate_compatibility_manifest(
            manifest,
            exercised_fixtures=_exercised_fixtures(),
        )


def test_compatibility_manifest_rejects_dispatch_function_drift(monkeypatch):
    monkeypatch.setitem(
        migration.ADAPTER_REGISTRY,
        "SUBFIELD_EDIT",
        lambda source_line: migration.adapt_subfield_edit(source_line),
    )

    with pytest.raises(migration.CompatibilityContractError, match="dispatch"):
        migration.validate_compatibility_manifest(
            _compatibility_manifest(),
            exercised_fixtures=_exercised_fixtures(),
        )


def test_compatibility_manifest_rejects_unidentified_fixture():
    exercised = _exercised_fixtures()
    exercised["different-fixture"] = exercised.pop("subfield-edit-literal")

    with pytest.raises(migration.CompatibilityContractError, match="fixture"):
        migration.validate_compatibility_manifest(
            _compatibility_manifest(),
            exercised_fixtures=exercised,
        )
