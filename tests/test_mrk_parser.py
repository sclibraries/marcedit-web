"""Unit tests for marcedit_web.lib.mrk_parser."""

from __future__ import annotations

import pytest

from marcedit_web.lib.mrk_parser import LineError, parse_mrk


# ---------------------------------------------------------------------------
# Happy-path tokenization
# ---------------------------------------------------------------------------


def test_parses_single_record_with_leader_control_and_variable():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  ocm12345\n"
        "=008  030415s2003    nyu    a      000 0 eng d\n"
        "=245  10$aTitle :$bsubtitle /$cby Author.\n"
    )
    records, file_errors = parse_mrk(text)
    assert file_errors == []
    assert len(records) == 1
    assert records[0].errors == []
    r = records[0].record
    assert r is not None
    assert r.get("001").data == "ocm12345"
    f245 = r.get("245")
    assert list(f245.indicators) == ["1", "0"]
    assert f245.get_subfields("a") == ["Title :"]
    assert f245.get_subfields("b") == ["subtitle /"]
    assert f245.get_subfields("c") == ["by Author."]


def test_blank_line_separates_records():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  AAA\n"
        "\n"
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  BBB\n"
    )
    records, _ = parse_mrk(text)
    assert len(records) == 2
    assert records[0].record.get("001").data == "AAA"
    assert records[1].record.get("001").data == "BBB"


def test_pipe_delimiter_accepted_on_input():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=245  10|aPipe title|bpipe subtitle\n"
    )
    records, _ = parse_mrk(text)
    f245 = records[0].record.get("245")
    assert f245.get_subfields("a") == ["Pipe title"]
    assert f245.get_subfields("b") == ["pipe subtitle"]


def test_backslash_in_indicators_means_blank():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=040  \\\\$aYUS$beng\n"
    )
    records, _ = parse_mrk(text)
    f040 = records[0].record.get("040")
    assert list(f040.indicators) == [" ", " "]


def test_backslash_in_control_field_means_space():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=008  260430t20252025ctuac\\\\\\ob\\\\\\\\001\\0\\eng\\d\n"
    )
    records, _ = parse_mrk(text)
    f008 = records[0].record.get("008")
    # Length 40 with the backslashes converted to spaces.
    assert len(f008.data) == 40
    assert "\\" not in f008.data


def test_leader_length_24_required_emits_error():
    text = (
        "=LDR  short\n"
        "=001  X\n"
    )
    records, _ = parse_mrk(text)
    codes = {e.code for e in records[0].errors}
    assert "ldr-length" in codes


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------


def test_bad_indicator_does_not_abort_parse():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=245  XY$aTitle\n"
    )
    records, _ = parse_mrk(text)
    codes = [e.code for e in records[0].errors]
    assert codes.count("bad-indicator") == 2
    # The line still produces a field.
    assert records[0].record.get("245").get_subfields("a") == ["Title"]


def test_bad_subfield_code_kept_with_error():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=245  10$@bad-code$aTitle\n"
    )
    records, _ = parse_mrk(text)
    codes = [e.code for e in records[0].errors]
    assert "bad-subfield-code" in codes
    # The bad code is kept verbatim so the round-trip preserves the input.
    f = records[0].record.get("245")
    sub_codes = [s.code for s in f.subfields]
    assert "@" in sub_codes
    assert "a" in sub_codes


def test_missing_indicators_get_padded():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=245\n"
    )
    # The `=245` line has only the tag + the two required spaces would be
    # missing; the regex requires two spaces so it should fall into bad-line.
    records, _ = parse_mrk(text)
    codes = [e.code for e in records[0].errors]
    assert "bad-line" in codes


def test_garbage_never_raises():
    parse_mrk("")
    parse_mrk("not a mrk file\n")
    parse_mrk("\x00\x01\x02 random junk")
    parse_mrk("=BAD_TAG_LINE_THAT_IS_NOT_THREE_CHARS  content\n")


def test_loose_data_before_first_delimiter_recovers():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=245  10loose-text$bsubtitle\n"
    )
    records, _ = parse_mrk(text)
    codes = [e.code for e in records[0].errors]
    assert "missing-leading-delimiter" in codes
    # The loose text is captured under `$a`.
    assert records[0].record.get("245").get_subfields("a") == ["loose-text"]
    assert records[0].record.get("245").get_subfields("b") == ["subtitle"]


def test_lines_without_equals_prefix_become_file_errors():
    text = (
        "this is not a mrk line\n"
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  AAA\n"
    )
    records, file_errors = parse_mrk(text)
    assert len(file_errors) == 1
    assert file_errors[0].code == "no-tag-prefix"
    # Records that follow still parse.
    assert records[0].record.get("001").data == "AAA"


def test_multiple_consecutive_blank_lines_are_harmless():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  AAA\n"
        "\n"
        "\n"
        "\n"
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  BBB\n"
    )
    records, _ = parse_mrk(text)
    assert len(records) == 2
    assert {records[0].record.get("001").data, records[1].record.get("001").data} == {"AAA", "BBB"}


# ---------------------------------------------------------------------------
# Line-pinning of errors
# ---------------------------------------------------------------------------


def test_line_error_pinned_to_source_line():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  AAA\n"
        "\n"
        "=LDR  short\n"
        "=001  BBB\n"
    )
    records, _ = parse_mrk(text)
    # The leader error in the SECOND record should be pinned to line 4.
    ldr_errs = [
        e for r in records for e in r.errors if e.code == "ldr-length"
    ]
    assert ldr_errs == [
        LineError(
            line_no=4,
            column=6,
            code="ldr-length",
            message=ldr_errs[0].message,  # message text is not pinned-down
            raw=ldr_errs[0].raw,
        )
    ]


def test_start_and_end_line_per_record():
    text = (
        "=LDR  00000nam a2200000 a 4500\n"  # line 1
        "=001  AAA\n"                       # line 2
        "\n"                                # line 3
        "=LDR  00000nam a2200000 a 4500\n"  # line 4
        "=001  BBB\n"                       # line 5
        "=245  10$aTitle\n"                 # line 6
    )
    records, _ = parse_mrk(text)
    assert (records[0].start_line, records[0].end_line) == (1, 2)
    assert (records[1].start_line, records[1].end_line) == (4, 6)
