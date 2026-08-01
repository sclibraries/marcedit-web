"""Fail-closed adapters for proven external task instructions (TASK-185)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


EMPTY_FIND_CHOICES = (
    "add_if_missing",
    "replace_existing",
    "ensure_one",
)


@dataclass(frozen=True)
class MigrationItem:
    source_line: str
    source_format: str
    status: str
    operation: dict[str, Any] | None = None
    reason: str = ""
    choices: tuple[str, ...] = ()
    instruction_sha256: str = ""


@dataclass(frozen=True)
class MigrationReview:
    items: tuple[MigrationItem, ...]

    @property
    def blocking_items(self) -> tuple[MigrationItem, ...]:
        return tuple(item for item in self.items if item.status != "converted")

    @property
    def converted_operations(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            item.operation
            for item in self.items
            if item.status == "converted" and item.operation is not None
        )


def _item(source_line: str, **kwargs: Any) -> MigrationItem:
    return MigrationItem(
        source_line=source_line,
        source_format="marcedit-tasksfile",
        instruction_sha256=hashlib.sha256(source_line.encode("utf-8")).hexdigest(),
        **kwargs,
    )


def adapt_subfield_edit(
    source_line: str,
    *,
    empty_find_choice: str | None = None,
) -> MigrationItem:
    """Convert only literal, nonempty SUBFIELD_EDIT semantics."""
    parts = source_line.rstrip("\n").split("\t")
    if len(parts) < 5 or parts[0].strip() != "SUBFIELD_EDIT":
        return _item(source_line, status="unresolved", reason="not a supported SUBFIELD_EDIT signature")
    tag, code, find, replacement = parts[1].strip(), parts[2].strip(), parts[3], parts[4]
    if find == "":
        if empty_find_choice not in EMPTY_FIND_CHOICES:
            return _item(
                source_line,
                status="choice_required",
                reason="empty Find has no implicit meaning; select an explicit policy",
                choices=EMPTY_FIND_CHOICES,
            )
        return _item(
            source_line,
            status="converted",
            reason=f"explicit empty-find policy: {empty_find_choice}",
            operation={
                "kind": "empty-find-subfield-policy",
                "params": {
                    "tag": tag,
                    "code": code,
                    "value": replacement,
                    "policy": empty_find_choice,
                },
            },
        )
    if find == "^b":
        return _item(source_line, status="unresolved", reason="^b syntax is not proven")
    if len(tag) != 3 or len(code) != 1:
        return _item(source_line, status="unresolved", reason="tag or subfield code is malformed")
    return _item(
        source_line,
        status="converted",
        operation={
            "kind": "guided-find-replace",
            "params": {
                "target_kind": "subfield",
                "tag": tag,
                "subfield": code,
                "match_mode": "contains",
                "find": find,
                "ignore_case": False,
                "replacement_mode": "matched_text",
                "replacement": replacement,
                "occurrences": "all",
                "value_scope": "all",
                "condition": "always",
            },
        },
    )


def adapt_instruction(source_line: str) -> MigrationItem:
    verb = source_line.split("\t", 1)[0].strip()
    if verb == "SUBFIELD_EDIT":
        return adapt_subfield_edit(source_line)
    if verb == "REPLACE":
        parts = source_line.rstrip("\n").split("\t")
        known = {
            (r"(=008.{25}).{1}(.+)", r"$1o$2"),
            (r"(=008.{31}).{1}(.+)", r"$1o$2"),
        }
        if len(parts) >= 3 and (parts[1], parts[2]) in known:
            return _item(
                source_line,
                status="converted",
                operation={"kind": "set-008-form", "params": {}},
            )
    if verb == "SORTBY":
        parts = source_line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[1].strip().upper() == "ALL":
            return _item(
                source_line,
                status="converted",
                operation={"kind": "sort-fields", "params": {}},
            )
    return _item(
        source_line,
        status="unresolved",
        reason=f"external instruction {verb or '(empty)'} has no proven adapter",
    )


def review_tasksfile(text: str) -> tuple[MigrationItem, ...]:
    """Review in source order without executing or silently dropping lines."""
    return tuple(
        adapt_instruction(line)
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


ADAPTER_REGISTRY = {
    "SUBFIELD_EDIT": adapt_subfield_edit,
}


def build_review(text: str) -> MigrationReview:
    return MigrationReview(items=review_tasksfile(text))
