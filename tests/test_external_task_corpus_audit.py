from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.audit_external_task_corpus import audit_corpus, main


PARTNER_CORPUS = (
    Path(__file__).parents[1]
    / "third_party"
    / "task-corpora"
    / "jenmawe-marcedit"
)


def _partner_corpus_or_skip() -> Path:
    if not PARTNER_CORPUS.is_dir():
        pytest.skip(
            "partner task corpus is unavailable in the Docker image; "
            "mount third_party/task-corpora read-only for the authoritative check"
        )
    return PARTNER_CORPUS


def test_audit_corpus_classifies_text_and_archive_entries(tmp_path):
    (tmp_path / "direct.tasksfile.txt").write_text(
        "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        "UNKNOWN\texternal intent\n",
        encoding="utf-8",
    )
    archive_path = tmp_path / "bundle.task"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "inside.txt",
            "SORTBY\tALL\tTrue\tTrue\n",
        )

    report = audit_corpus(tmp_path)

    assert len(report.documents) == 2
    assert len(report.items) == 3
    assert report.converted == 2
    assert report.blockers == 1
    assert report.unclassified == ()
    assert report.items_without_next_action == ()


def test_audit_corpus_reports_unknown_instruction_with_next_action(tmp_path):
    (tmp_path / "empty.tasksfile.txt").write_text(
        "UNKNOWN\tvalue\n", encoding="utf-8"
    )
    report = audit_corpus(tmp_path)

    assert report.blockers == 1
    assert report.items[0].item.recommended_operation == "choose-operation"
    assert report.items_without_next_action == ()


def test_audit_cli_prints_cataloger_action_for_generic_blocker(
    tmp_path, capsys
):
    (tmp_path / "unknown.tasksfile.txt").write_text(
        "TASK_LIST\texternal intent\n", encoding="utf-8"
    )

    assert main([str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "action=Import the referenced task file or select an already imported task" in output


def test_partner_corpus_matches_pinned_manifest_and_remains_actionable():
    corpus = _partner_corpus_or_skip()
    manifest = json.loads(
        (corpus / "manifest.json").read_text(encoding="utf-8")
    )
    archives = corpus / "FOLIO Marc Edit Tasks"
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in archives.glob("*.task")
    }

    assert manifest["source_commit"] == (
        "d07377a58cba9d0936a63863c9d428498609d5e5"
    )
    assert actual == manifest["sha256"]

    report = audit_corpus(corpus)
    assert len(report.documents) == 49
    assert len(report.items) == 1239
    assert report.unclassified == ()
    assert report.items_without_next_action == ()


def test_checked_in_partner_report_matches_corpus_totals():
    corpus = _partner_corpus_or_skip()
    report = audit_corpus(corpus)
    text = (
        corpus.parents[2] / "docs" / "partner-task-corpus-report.md"
    )
    if not text.exists():
        pytest.skip(
            "partner corpus report is unavailable in the Docker image; "
            "mount docs read-only for the authoritative check"
        )
    text = text.read_text(encoding="utf-8")

    assert f"- Documents: {len(report.documents):,}" in text
    assert f"- Instructions: {len(report.items):,}" in text
    assert f"- Converted by proven adapters: {report.converted:,}" in text
    assert f"- Actionable blockers: {report.blockers:,}" in text
    assert "- Unclassified instructions: 0" in text
    assert "- Blockers without a cataloger next action: 0" in text
