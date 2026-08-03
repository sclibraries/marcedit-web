from __future__ import annotations

import zipfile

from scripts.audit_external_task_corpus import audit_corpus


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
