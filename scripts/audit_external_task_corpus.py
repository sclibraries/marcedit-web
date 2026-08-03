#!/usr/bin/env python3
"""Audit a local MarcEdit task corpus without exposing it in fixtures.

The corpus is intentionally local and may contain institutional values. The
default report prints paths, counts, adapter outcomes, and source locations;
source lines are included only with ``--technical``.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from marcedit_web.lib import external_task_migration


@dataclass(frozen=True)
class AuditItem:
    document: str
    line_number: int
    item: external_task_migration.MigrationItem


@dataclass(frozen=True)
class AuditReport:
    documents: tuple[str, ...]
    items: tuple[AuditItem, ...]

    @property
    def converted(self) -> int:
        return sum(item.item.status == "converted" for item in self.items)

    @property
    def blockers(self) -> int:
        return sum(item.item.status != "converted" for item in self.items)

    @property
    def unclassified(self) -> tuple[AuditItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.item.status not in {"converted", "unresolved"}
        )

    @property
    def items_without_next_action(self) -> tuple[AuditItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.item.status != "converted"
            and not item.item.recommended_operation
            and not item.item.cataloger_action
        )


def _source_documents(root: Path) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.txt")):
        documents.append((str(path.relative_to(root)), path.read_text(
            encoding="utf-8", errors="replace"
        )))
    for path in sorted(root.rglob("*.task")):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith(".txt"):
                    entry = f"{path.relative_to(root)}::{name}"
                    documents.append((entry, archive.read(name).decode(
                        "utf-8", errors="replace"
                    )))
    return documents


def audit_corpus(root: Path) -> AuditReport:
    """Classify every non-comment instruction in every corpus document."""

    documents = _source_documents(root)
    items: list[AuditItem] = []
    for document, text in documents:
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip() or line.startswith("#"):
                continue
            item = external_task_migration.review_tasksfile(line)[0]
            items.append(AuditItem(document, line_number, item))
    return AuditReport(tuple(document for document, _ in documents), tuple(items))


def _print_report(report: AuditReport, *, technical: bool) -> None:
    print(
        "documents={0} instructions={1} converted={2} blockers={3}".format(
            len(report.documents),
            len(report.items),
            report.converted,
            report.blockers,
        )
    )
    for document in report.documents:
        entries = [item for item in report.items if item.document == document]
        converted = sum(item.item.status == "converted" for item in entries)
        print(
            "document={0} instructions={1} converted={2} blockers={3}".format(
                document,
                len(entries),
                converted,
                len(entries) - converted,
            )
        )
    for entry in report.items:
        item = entry.item
        if item.status == "converted" and not technical:
            continue
        print(
            "{0}:{1} status={2} recommendation={3} reason={4}".format(
                entry.document,
                entry.line_number,
                item.status,
                item.recommended_operation or "none",
                " ".join(item.reason.split()) or "none",
            )
        )
        if technical:
            print("  source={0}".format(item.source_line))
    if report.unclassified:
        print(
            "ERROR unclassified_items={0}".format(len(report.unclassified)),
            file=sys.stderr,
        )
    if report.items_without_next_action:
        print(
            "ERROR items_without_next_action={0}".format(
                len(report.items_without_next_action)
            ),
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument(
        "--technical",
        action="store_true",
        help="include source lines and converted adapter details",
    )
    args = parser.parse_args(argv)
    if not args.corpus.is_dir():
        parser.error(f"corpus directory does not exist: {args.corpus}")
    report = audit_corpus(args.corpus)
    _print_report(report, technical=args.technical)
    return 1 if report.unclassified or report.items_without_next_action else 0


if __name__ == "__main__":
    raise SystemExit(main())
