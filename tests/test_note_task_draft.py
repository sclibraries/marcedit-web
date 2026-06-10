"""Tests for deterministic cataloger-note task drafting."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from marcedit_web.lib import note_task_draft


def test_clean_syntax_parses_common_operations():
    review = note_task_draft.draft_task_from_notes(
        """
        Task: Routledge EBA
        Description: Routledge cleanup
        replace field 001 "^TFeba" with "SCTFEBA"
        replace subfield 856 u "http://old" with "https://new"
        change subfield 856 z to y
        add field 710 2_ $aRoutledge EBA
        add field 852 8_ $hOnline $bSmith College Online
        delete tag 029
        """
    )

    assert review.task_name == "routledge-eba"
    assert review.description == "Routledge cleanup"
    assert [op.kind for op in review.operations] == [
        "replace-field-data-by-regex",
        "subfield-replace",
        "copy-subfield",
        "delete-subfield",
        "add-field",
        "add-field",
        "delete-tag",
    ]
    assert review.operations[0].params["pattern"] == "^TFeba"
    assert review.operations[2].params == {
        "tag": "856",
        "src_code": "z",
        "dst_code": "y",
    }
    assert review.operations[4].params["subfields"] == [["a", "Routledge EBA"]]
    assert review.operations[5].params["subfields"] == [
        ["h", "Online"],
        ["b", "Smith College Online"],
    ]
    assert review.rejected_operations == ()


def test_marcedit_add_field_block_parses():
    review = note_task_draft.draft_task_from_notes(
        """
        Add field (710)
            710
            2\\$aRoutledge EBA
        """
    )

    assert [op.kind for op in review.operations] == ["add-field"]
    assert review.operations[0].params == {
        "tag": "710",
        "ind1": "2",
        "ind2": " ",
        "subfields": [["a", "Routledge EBA"]],
        "condition": "always",
        "if_absent": False,
    }


def test_parses_streaming_audio_add_field_prose():
    review = note_task_draft.draft_task_from_notes(
        "add 877 subfield m Streaming Audio when leader type is i or j"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].kind == "add-field"
    assert review.operations[0].params == {
        "tag": "877",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["m", "Streaming Audio"]],
        "condition": "audios",
        "if_absent": False,
    }


def test_parses_scores_genre_heading_add_field_prose():
    review = note_task_draft.draft_task_from_notes(
        "add 655 indicator 2 7 subfield a Electronic scores. subfield 2 local "
        "when leader type is c or d"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params == {
        "tag": "655",
        "ind1": " ",
        "ind2": "7",
        "subfields": [["a", "Electronic scores."], ["2", "local"]],
        "condition": "scores",
        "if_absent": False,
    }


def test_parses_notated_music_add_field_prose():
    review = note_task_draft.draft_task_from_notes(
        "add 655 second indicator 7 subfield a Electronic scores. "
        "subfield 2 local when leader indicates notated music"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params["condition"] == "scores"
    assert review.operations[0].params["subfields"] == [
        ["a", "Electronic scores."],
        ["2", "local"],
    ]


def test_rejects_unsupported_add_field_when_clause():
    line = "add 877 subfield m Streaming Audio when LDR type is i or j"
    review = note_task_draft.draft_task_from_notes(line)

    assert review.operations == ()
    assert review.unsupported_lines == (line,)


def test_parses_add_field_indicator_after_subfield_value():
    review = note_task_draft.draft_task_from_notes(
        "add 655 subfield a Electronic scores. indicator 2 7 "
        "when leader type is c or d"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params == {
        "tag": "655",
        "ind1": " ",
        "ind2": "7",
        "subfields": [["a", "Electronic scores."]],
        "condition": "scores",
        "if_absent": False,
    }


def test_add_field_without_when_ignores_condition_words_in_subfield_value():
    review = note_task_draft.draft_task_from_notes(
        "add 500 subfield a Notated music"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params == {
        "tag": "500",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["a", "Notated music"]],
        "condition": "always",
        "if_absent": False,
    }


def test_add_field_rejects_unsupported_when_after_condition_words_in_value():
    line = "add 500 subfield a Notated music when LDR type is x"
    review = note_task_draft.draft_task_from_notes(line)

    assert review.operations == ()
    assert review.unsupported_lines == (line,)


def test_add_field_rejects_supported_when_substring_with_extra_condition():
    line = (
        "add 877 subfield m Streaming Audio "
        "when leader type is i or j and tag 300 exists"
    )
    review = note_task_draft.draft_task_from_notes(line)

    assert review.operations == ()
    assert review.unsupported_lines == (line,)


def test_add_field_value_starting_with_when_is_not_condition_clause():
    review = note_task_draft.draft_task_from_notes(
        "add 500 subfield a When we were young"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params == {
        "tag": "500",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["a", "When we were young"]],
        "condition": "always",
        "if_absent": False,
    }


def test_add_field_value_with_when_leader_text_is_not_condition_clause():
    review = note_task_draft.draft_task_from_notes(
        "add 500 subfield a Work about when leader type is c or d"
    )

    assert review.unsupported_lines == ()
    assert len(review.operations) == 1
    assert review.operations[0].params == {
        "tag": "500",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["a", "Work about when leader type is c or d"]],
        "condition": "always",
        "if_absent": False,
    }


def test_add_field_rejects_embedded_when_followed_by_condition_clause():
    line = (
        "add 500 subfield a Work about when leader type is c or d "
        "when leader type is i or j"
    )
    review = note_task_draft.draft_task_from_notes(line)

    assert review.operations == ()
    assert review.unsupported_lines == (line,)


def test_add_field_rejects_supported_when_followed_by_extra_when_clause():
    line = (
        "add 877 subfield m Streaming Audio "
        "when leader type is i or j when tag 300 exists"
    )
    review = note_task_draft.draft_task_from_notes(line)

    assert review.operations == ()
    assert review.unsupported_lines == (line,)


def test_marcedit_edit_field_001_block_parses_prefix_replace():
    review = note_task_draft.draft_task_from_notes(
        """
        Edit field (001)
            001
            TFeba
            SCTFEBA
        """
    )

    assert [op.kind for op in review.operations] == ["replace-field-data-by-regex"]
    assert review.operations[0].params == {
        "tag": "001",
        "pattern": "^TFeba",
        "replacement": "SCTFEBA",
        "ignore_case": False,
    }


def test_routledge_style_note_parses_unambiguous_lines():
    notes = """
    Routledge EBA

    FTP login saved in LastPass as "Gobi"

    Run the core custom catalog steps

    Edit field (001)
        001
        TFeba
        SCTFEBA

    Add field (852)
        852
        8\\$hOnline$bSmith College Online

    Add field (710)
        710
        2\\$aRoutledge EBA

    Find/replace
        $zSmith: Link to resource
        $ySmith: Link to resource

    Find/replace
        http://libproxy.smith.edu:2048/login?url=
        https://libproxy.smith.edu/login?url=

    Manual MarcEdit tasks
    Tools menu: Remove blank subfields
    """
    review = note_task_draft.draft_task_from_notes(notes)

    assert "Routledge EBA" in review.description
    assert [op.kind for op in review.operations] == [
        "replace-field-data-by-regex",
        "add-field",
        "add-field",
        "copy-subfield",
        "delete-subfield",
        "subfield-replace",
    ]
    assert any("LastPass" in note for note in review.manual_notes)
    assert any("core custom catalog" in q for q in review.questions)
    assert any("Remove blank subfields" in line for line in review.unsupported_lines)


def test_notes_starting_with_structural_heading_use_generic_task_name():
    review = note_task_draft.draft_task_from_notes(
        """
        Find/replace
            $zSmith: Link to resource
            $ySmith: Link to resource
        """
    )

    assert review.task_name == "draft-from-notes"


def test_proxy_find_replace_ignores_trailing_parenthetical_notes():
    review = note_task_draft.draft_task_from_notes(
        """
        Find/replace
            http://libproxy.smith.edu:2048/login?url=      (ie, OLD PROXY)
            https://libproxy.smith.edu/login?url=          (ie, NEW PROXY)
        """
    )

    assert len(review.operations) == 1
    assert review.operations[0].params["find"] == (
        "http://libproxy.smith.edu:2048/login?url="
    )
    assert review.operations[0].params["replace"] == (
        "https://libproxy.smith.edu/login?url="
    )


def test_subfield_change_summary_avoids_markdown_dollar_artifacts():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    review = note_task_draft.draft_task_from_notes(
        """
        Find/replace
            $zSmith: Link to resource
            $ySmith: Link to resource
        """
    )

    summary = tasks_render._ai_draft_operation_summary(review.operations[0])

    assert "subfield z" in summary
    assert "subfield y" in summary
    assert "$z" not in summary
    assert "$y" not in summary


def test_ambiguous_lines_are_preserved_not_guessed():
    review = note_task_draft.draft_task_from_notes(
        """
        Find/replace
            =035  \\\\$aTFeba
            =035  9\\$a(SCTFEBA)
        Edit subfield (remove :-only fields)
            300
            b
            :
        """
    )

    assert review.operations == ()
    assert len(review.unsupported_lines) == 2


def test_help_text_documents_supported_syntax():
    text = note_task_draft.help_text()

    assert "replace field 001" in text
    assert "add field 710 2_" in text
    assert "change subfield 856 z to y" in text


def test_unresolved_text_feeds_gemini_fallback():
    review = note_task_draft.draft_task_from_notes(
        "Run the core custom catalog steps"
    )

    assert "core custom catalog" in note_task_draft.unresolved_text(review)


def test_gemini_fallback_available_only_for_unresolved_text(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    unresolved = note_task_draft.draft_task_from_notes(
        "Run the core custom catalog steps"
    )
    resolved = note_task_draft.draft_task_from_notes("delete tag 029")

    monkeypatch.setattr(tasks_render.gemini_task_draft, "is_enabled", lambda: True)
    assert tasks_render._ai_fallback_available(unresolved) is True
    assert tasks_render._ai_fallback_available(resolved) is False

    monkeypatch.setattr(tasks_render.gemini_task_draft, "is_enabled", lambda: False)
    assert tasks_render._ai_fallback_available(unresolved) is False


def test_fallback_review_merges_with_deterministic_draft():
    base = note_task_draft.draft_task_from_notes(
        """
        Task: Routledge EBA
        delete tag 029
        Run the core custom catalog steps
        """
    )
    fallback = note_task_draft.draft_task_from_notes(
        "add field 710 2_ $aRoutledge EBA"
    )

    merged = note_task_draft.merge_fallback_review(base, fallback)

    assert merged.task_name == "routledge-eba"
    assert [op.kind for op in merged.operations] == ["delete-tag", "add-field"]
    assert merged.questions == ()
    assert merged.unsupported_lines == ()
