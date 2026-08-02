"""Fail-closed adapters for proven external task instructions (TASK-185)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping


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


class CompatibilityContractError(ValueError):
    """Raised when checked-in compatibility evidence drifts from code."""


@dataclass(frozen=True)
class CompatibilityAdapter:
    adapter: Callable[..., MigrationItem]
    verbs: tuple[str, ...]
    shape_ids: tuple[str, ...]
    fixture_ids: tuple[str, ...]


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
    if find.startswith("^"):
        return _item(
            source_line,
            status="unresolved",
            reason="caret-prefixed syntax is not proven",
        )
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


def adapt_replace(source_line: str) -> MigrationItem:
    parts = source_line.rstrip("\n").split("\t")
    known_positions = {
        (r"(=008.{25}).{1}(.+)", r"$1o$2"): "23",
        (r"(=008.{31}).{1}(.+)", r"$1o$2"): "29",
    }
    position = known_positions.get(tuple(parts[1:3])) if len(parts) >= 3 else None
    if position is not None:
        return _item(
            source_line,
            status="converted",
            operation={"kind": "set-008-form", "params": {"position": position}},
        )
    return _item(source_line, status="unresolved", reason="REPLACE signature has no proven adapter")


def adapt_sortby(source_line: str) -> MigrationItem:
    parts = source_line.rstrip("\n").split("\t")
    if len(parts) >= 2 and parts[1].strip().upper() == "ALL":
        return _item(
            source_line,
            status="converted",
            operation={"kind": "sort-fields", "params": {}},
        )
    return _item(source_line, status="unresolved", reason="SORTBY signature has no proven adapter")


ADAPTER_REGISTRY = {
    "SUBFIELD_EDIT": adapt_subfield_edit,
    "REPLACE": adapt_replace,
    "SORTBY": adapt_sortby,
}

COMPATIBILITY_ADAPTER_REGISTRY = {
    "subfield-edit-v1": CompatibilityAdapter(
        adapter=adapt_subfield_edit,
        verbs=("SUBFIELD_EDIT",),
        shape_ids=("subfield-edit-literal",),
        fixture_ids=("subfield-edit-literal",),
    ),
}


def _manifest_values(entry: Mapping[str, Any], field: str) -> tuple[str, ...]:
    values = entry.get(field)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
        or len(values) != len(set(values))
    ):
        raise CompatibilityContractError(
            f"compatibility adapter {field} must be unique nonempty strings"
        )
    return tuple(values)


def validate_compatibility_manifest(
    manifest: Mapping[str, Any],
    *,
    exercised_fixtures: Mapping[str, str],
) -> None:
    """Fail closed when manifest, dispatch, or fixture evidence drifts."""
    if manifest.get("schema_version") != 1:
        raise CompatibilityContractError("unsupported compatibility schema version")
    entries = manifest.get("adapters")
    if not isinstance(entries, list) or not entries:
        raise CompatibilityContractError("compatibility adapters must be nonempty")

    manifest_adapters = {}
    required_fields = {"adapter_id", "verbs", "shape_ids", "fixture_ids"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required_fields:
            raise CompatibilityContractError(
                "compatibility adapter fields do not match schema"
            )
        adapter_id = entry["adapter_id"]
        if not isinstance(adapter_id, str) or not adapter_id:
            raise CompatibilityContractError("adapter_id must be nonempty")
        if adapter_id in manifest_adapters:
            raise CompatibilityContractError(f"duplicate adapter_id {adapter_id}")
        manifest_adapters[adapter_id] = {
            "verbs": _manifest_values(entry, "verbs"),
            "shape_ids": _manifest_values(entry, "shape_ids"),
            "fixture_ids": _manifest_values(entry, "fixture_ids"),
        }

    if manifest_adapters.keys() != COMPATIBILITY_ADAPTER_REGISTRY.keys():
        raise CompatibilityContractError(
            "manifest adapter IDs do not match registered adapters"
        )

    registered_fixture_ids = set()
    for adapter_id, registered in COMPATIBILITY_ADAPTER_REGISTRY.items():
        actual = manifest_adapters[adapter_id]
        for field in ("verbs", "shape_ids", "fixture_ids"):
            if actual[field] != getattr(registered, field):
                raise CompatibilityContractError(
                    f"manifest {adapter_id} {field} drifted from registration"
                )
        for verb in registered.verbs:
            if ADAPTER_REGISTRY.get(verb) is not registered.adapter:
                raise CompatibilityContractError(
                    f"registered adapter {adapter_id} dispatch drifted for {verb}"
                )
        registered_fixture_ids.update(registered.fixture_ids)
        exercised_shapes = {
            exercised_fixtures.get(fixture_id)
            for fixture_id in registered.fixture_ids
        }
        if None in exercised_shapes or exercised_shapes != set(
            registered.shape_ids
        ):
            raise CompatibilityContractError(
                f"registered adapter {adapter_id} fixture evidence drifted"
            )

    if set(exercised_fixtures) != registered_fixture_ids:
        raise CompatibilityContractError(
            "exercised fixture IDs do not match registered fixtures"
        )


def adapt_instruction(source_line: str) -> MigrationItem:
    verb = source_line.split("\t", 1)[0].strip()
    adapter = ADAPTER_REGISTRY.get(verb)
    if adapter is not None:
        return adapter(source_line)
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


def build_review(text: str) -> MigrationReview:
    return MigrationReview(items=review_tasksfile(text))
