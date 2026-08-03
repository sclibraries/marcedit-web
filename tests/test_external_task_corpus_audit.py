from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

from scripts.audit_external_task_corpus import audit_corpus, main


PARTNER_CORPUS = (
    Path(__file__).parents[1]
    / "third_party"
    / "task-corpora"
    / "jenmawe-marcedit"
)


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
    assert "action=Choose the closest structured operation" in output


def test_partner_corpus_matches_pinned_manifest_and_remains_actionable():
    manifest = json.loads(
        (PARTNER_CORPUS / "manifest.json").read_text(encoding="utf-8")
    )
    archives = PARTNER_CORPUS / "FOLIO Marc Edit Tasks"
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in archives.glob("*.task")
    }

    assert manifest["source_commit"] == (
        "d07377a58cba9d0936a63863c9d428498609d5e5"
    )
    assert actual == manifest["sha256"]

    report = audit_corpus(PARTNER_CORPUS)
    assert len(report.documents) == 49
    assert len(report.items) == 1239
    assert report.unclassified == ()
    assert report.items_without_next_action == ()
