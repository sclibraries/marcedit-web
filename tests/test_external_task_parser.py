from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from marcedit_web.lib.external_task_parser import (
    ExternalParseError,
    instruction_shape,
    parse_instruction,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "external_task_migration"
    / "parser-shapes.tasksfile.txt"
)


def test_parse_add_preserves_empty_condition_and_provenance():
    item = parse_instruction(
        "ADD\t506\t1\\$aAccess.$5ABC\t100\t",
        source_entry="core.tasksfile.txt",
        line_number=7,
    )

    assert item.verb == "ADD"
    assert item.arguments == ("506", "1\\$aAccess.$5ABC", "100", "")
    assert item.option_code == 100
    assert (item.source_entry, item.line_number) == ("core.tasksfile.txt", 7)
    assert item.instruction_sha256 == (
        "0376f8cdef29abc33919e263a453c2212f2ccf4b76b2d29133c204df7ff450c0"
    )


def test_parse_normalizes_crlf_before_storing_and_hashing():
    item = parse_instruction("SORTBY\tALL\tTrue\tTrue\r\n")

    assert item.source_line == "SORTBY\tALL\tTrue\tTrue"
    assert item.instruction_sha256 == (
        "9e41bb5e7e170654b56db89e616c7fffadc5157bb47c55ec2678d822003c28ad"
    )


def test_parsed_instruction_is_immutable():
    item = parse_instruction("SORTBY\tALL\tTrue\tTrue")

    with pytest.raises(FrozenInstanceError):
        item.verb = "ADD"


@pytest.mark.parametrize(
    ("line", "verb", "option_code", "boolean_flags"),
    [
        ("ADD\t506\t\\$aOpen\t100\t", "ADD", 100, ()),
        (
            "COPY\t856\t857\tfalse\t$3SOURCE\t\tfalse\t",
            "COPY",
            None,
            (False, False),
        ),
        (
            "DELETE\t9XX\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse",
            "DELETE",
            0,
            (False,) * 5,
        ),
        ("EDITFIELD\t001\t\\\t0\t\t", "EDITFIELD", 0, ()),
        (
            "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0",
            "RDAHELPER",
            None,
            (),
        ),
        ("REPLACE\tfoo\tbar\t0\t\t1", "REPLACE", 0, ()),
        ("REPLACE\tfoo\tbar\t2\tcondition\t2\tFalse", "REPLACE", 2, (False,)),
        ("SORTBY\tALL\tTrue\tTrue", "SORTBY", None, (True, True)),
        ("SUBFIELD_EDIT\t035\ta\tOLD\tNEW\t0|0", "SUBFIELD_EDIT", 0, ()),
        ("SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0", "SUBFIELD_REMOVE", 107, ()),
        (
            "buildnewfield\t=035  9\\$a{001}\tFalse\tFalse\tTrue\tFalse",
            "buildnewfield",
            None,
            (False, False, True, False),
        ),
    ],
)
def test_each_corpus_verb_decodes_its_typed_options(
    line, verb, option_code, boolean_flags
):
    item = parse_instruction(line)

    assert item.verb == verb
    assert item.option_code == option_code
    assert item.boolean_flags == boolean_flags


@pytest.mark.parametrize(
    "line",
    [
        "ADD\t506\t\\$aOpen\t100",
        "COPY\t856\t857\tfalse\t$3SOURCE\t\tfalse",
        "DELETE\t9XX\t\t0\tFalse\tFalse\tFalse\tFalse",
        "EDITFIELD\t001\t\\\t0\t",
        "RDAHELPER",
        "REPLACE\tfoo\tbar\t0\t",
        "SORTBY\tALL\tTrue",
        "SUBFIELD_EDIT\t035\ta\tOLD\tNEW",
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)",
        "buildnewfield\t=035  9\\$a{001}\tFalse\tFalse\tTrue",
    ],
)
def test_each_corpus_verb_rejects_missing_required_columns(line):
    with pytest.raises(ExternalParseError, match="requires"):
        parse_instruction(line)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("ADD\t506\t\\$aOpen\tnot-a-number\t", "ADD option"),
        ("ADD\t506\t\\$aOpen\t 100\t", "ADD option"),
        ("DELETE\t9XX\t\tnone\tFalse\tFalse\tFalse\tFalse\tFalse", "DELETE option"),
        ("EDITFIELD\t001\t\\\tall\t\t", "EDITFIELD option"),
        ("REPLACE\tfoo\tbar\tall\t\t1", "REPLACE option 1"),
        ("REPLACE\tfoo\tbar\t0\t\tlast", "REPLACE option 2"),
        ("SUBFIELD_EDIT\t035\ta\tOLD\tNEW\tzero|0", "SUBFIELD_EDIT option"),
        ("SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|last", "SUBFIELD_REMOVE option"),
    ],
)
def test_numeric_options_reject_malformed_values(line, message):
    with pytest.raises(ExternalParseError, match=message):
        parse_instruction(line)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "buildnewfield\t=035  9\\$a{001}\tFalse\tFalse\tmaybe\tFalse",
            "Build Field flag 3",
        ),
        ("COPY\t856\t857\tyes\t$3SOURCE\t\tfalse\t", "COPY flag 1"),
        ("DELETE\t9XX\t\t0\tFalse\tFalse\t1\tFalse\tFalse", "DELETE flag 3"),
        ("REPLACE\tfoo\tbar\t0\t\t1\tno", "REPLACE flag 1"),
        ("SORTBY\tALL\tTrue\t1", "SORTBY flag 2"),
    ],
)
def test_boolean_options_reject_non_boolean_values(line, message):
    with pytest.raises(ExternalParseError, match=message):
        parse_instruction(line)


def test_rdahelper_requires_all_18_serialized_positions():
    with pytest.raises(ExternalParseError, match="18 pipe-delimited positions"):
        parse_instruction("RDAHELPER\t1|1|0|language of cataloging|0")


def test_empty_surplus_columns_are_preserved_but_nonempty_surplus_fails_closed():
    item = parse_instruction(
        "DELETE\t506\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\t"
    )
    assert item.arguments[-1] == ""

    with pytest.raises(ExternalParseError, match="nonempty surplus column 5"):
        parse_instruction("ADD\t877\t\\\\$mImage\t106\t/=LDR.{8}k.+/\t100\t")


@pytest.mark.parametrize("line", ["", " \tvalue", "UNKNOWN\tvalue"])
def test_missing_or_unknown_verbs_fail_closed(line):
    with pytest.raises(ExternalParseError):
        parse_instruction(line)


def test_parser_fixture_exercises_registered_literal_shape():
    items = [parse_instruction(line) for line in FIXTURE.read_text().splitlines()]

    assert [instruction_shape(item) for item in items] == [
        "subfield-edit-literal"
    ]


def test_instruction_shape_is_value_neutral_for_literal_subfield_edits():
    first = parse_instruction("SUBFIELD_EDIT\t035\ta\tOLD\tNEW\t0|0")
    second = parse_instruction("SUBFIELD_EDIT\t856\tu\tbefore\tafter\t0|0")

    assert instruction_shape(first) == "subfield-edit-literal"
    assert instruction_shape(second) == "subfield-edit-literal"
