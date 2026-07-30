"""Synthetic and optional local-corpus coverage for task authoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import marcedit_import, task_authoring


FIXTURES = Path(__file__).parent / "fixtures" / "task_authoring"
REFERENCE = (
    Path(__file__).parents[1] / "docs" / "task-authoring-syntax.md"
)
CORPUS = Path(__file__).parents[1] / "MarcEdit Tasks"


def _smith_035_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "035",
            "ind1": "9",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                    ],
                ]
            ],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
        },
    }


def _smith_876_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "B("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                        {"type": "text", "value": "-SC"},
                    ],
                ],
                ["l", [{"type": "text", "value": "Internet"}]],
            ],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
        },
    }


def test_smith_core_instance_fixture_contains_035_and_visible_rda_gap():
    text = (
        FIXTURES / "smith-core-instance.tasksfile.txt"
    ).read_text(encoding="utf-8")
    assert "=035  9\\$a({003}){001}" in text
    assert "RDAHELPER" in text


def test_holdings_fixture_contains_876_and_add_examples():
    text = (
        FIXTURES / "smith-core-holdings-items.tasksfile.txt"
    ).read_text(encoding="utf-8")
    assert "=876  \\\\$aB({003}){001}-SC$lInternet" in text
    assert "ADD\t852" in text
    assert "ADD\t877" in text


def test_reference_examples_match_executable_mnemonics():
    if not REFERENCE.exists():
        pytest.skip(
            "task-authoring syntax reference is unavailable in the Docker "
            "build context; mount it read-only for the authoritative check"
        )
    reference = REFERENCE.read_text(encoding="utf-8")
    assert task_authoring.render_mnemonic(
        _smith_035_operation()
    ) in reference
    assert task_authoring.render_mnemonic(
        _smith_876_operation()
    ) in reference
    assert "RDAHELPER" in reference
    assert "not supported" in reference.lower()


def test_local_task_corpus_add_and_build_signatures_are_classified():
    if not CORPUS.exists():
        pytest.skip(
            "institutional MarcEdit Tasks corpus is unavailable; "
            "synthetic fixtures remain authoritative"
        )
    task_files = sorted(CORPUS.rglob("*.txt"))
    if not task_files:
        pytest.fail(
            "MarcEdit Tasks exists but contains no readable .txt definitions"
        )
    outcomes = []
    for task_file in task_files:
        for line in task_file.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("ADD\t") or line.startswith(
                "buildnewfield\t"
            ):
                result = marcedit_import.convert_tasksfile_text(
                    line + "\n",
                    name="classification",
                    description_fallback="",
                )
                outcomes.append(
                    "unresolved" if result.unsupported else "exact"
                )
    assert outcomes, "corpus has no Add Field or Build Field signatures"
    assert set(outcomes) <= {"exact", "unresolved"}
