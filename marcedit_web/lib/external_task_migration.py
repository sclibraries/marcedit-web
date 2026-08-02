"""Fail-closed adapters for proven external task instructions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .external_field_syntax import (
    parse_build_template,
    parse_leader_condition,
    parse_mnemonic_field,
)
from .external_task_parser import (
    ExternalInstruction,
    ExternalParseError,
    parse_instruction,
)
from .rda_operations import smith_external_material_operation


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
    operations: tuple[dict[str, Any], ...] = ()
    reason: str = ""
    choices: tuple[str, ...] = ()
    instruction_sha256: str = ""
    intent: str = ""
    recommended_operation: str = ""
    prefilled_params: dict[str, Any] | None = None
    cataloger_action: str = ""
    disclosure: str = ""

    @property
    def operation(self) -> dict[str, Any] | None:
        """Temporary singular accessor retained for one compatibility cycle."""

        return self.operations[0] if len(self.operations) == 1 else None


@dataclass(frozen=True)
class MigrationReview:
    items: tuple[MigrationItem, ...]

    @property
    def blocking_items(self) -> tuple[MigrationItem, ...]:
        return tuple(item for item in self.items if item.status != "converted")

    @property
    def converted_operations(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            operation
            for item in self.items
            if item.status == "converted"
            for operation in item.operations
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
    operation = kwargs.pop("operation", None)
    if operation is not None:
        if "operations" in kwargs:
            raise TypeError("provide operation or operations, not both")
        kwargs["operations"] = (operation,)
    return MigrationItem(
        source_line=source_line.rstrip("\r\n"),
        source_format="marcedit-tasksfile",
        instruction_sha256=hashlib.sha256(
            source_line.rstrip("\r\n").encode("utf-8")
        ).hexdigest(),
        **kwargs,
    )


def _suggestion(
    source_line: str,
    *,
    intent: str,
    reason: str,
    recommended_operation: str,
    prefilled_params: dict[str, Any] | None,
    cataloger_action: str,
) -> MigrationItem:
    return _item(
        source_line,
        status="unresolved",
        intent=intent,
        reason=reason,
        recommended_operation=recommended_operation,
        prefilled_params=dict(prefilled_params or {}),
        cataloger_action=cataloger_action,
    )


def _safe_field_params(tag: str, field_data: str) -> dict[str, Any]:
    try:
        return parse_mnemonic_field("={0}  {1}".format(tag, field_data))
    except ValueError:
        return {"tag": tag} if tag else {}


def _safe_build_params(template: str) -> dict[str, Any]:
    try:
        return parse_build_template(template)
    except ValueError:
        return {}


def _is_data_tag(value: object) -> bool:
    return bool(re.fullmatch(r"\d{3}", str(value))) and not str(value).startswith(
        "00"
    )


def _core_parse_failure(source_line: str, exc: ExternalParseError) -> MigrationItem:
    parts = source_line.rstrip("\r\n").split("\t")
    verb = parts[0].strip() if parts else ""
    if verb == "ADD":
        tag = parts[1].strip() if len(parts) > 1 else ""
        field_data = parts[2] if len(parts) > 2 else ""
        params = _safe_field_params(tag, field_data)
        return _suggestion(
            source_line,
            intent="Add a MARC field using the external option policy",
            reason=exc.message,
            recommended_operation="add-field",
            prefilled_params=params,
            cataloger_action=(
                "Open Add Field, review the prefilled field, and choose an "
                "explicit existing-field policy."
            ),
        )
    if verb == "DELETE":
        tag = parts[1].strip() if len(parts) > 1 else ""
        return _suggestion(
            source_line,
            intent="Delete selected MARC fields",
            reason=exc.message,
            recommended_operation="delete-tag",
            prefilled_params={"tag": tag} if tag else {},
            cataloger_action=(
                "Open Delete Tag and confirm how the unsupported external "
                "option should affect matching fields."
            ),
        )
    if verb == "buildnewfield":
        template = parts[1] if len(parts) > 1 else ""
        return _suggestion(
            source_line,
            intent="Build a MARC field from source record values",
            reason=exc.message,
            recommended_operation="build-field",
            prefilled_params=_safe_build_params(template),
            cataloger_action=(
                "Open Build Field, review the template, and select explicit "
                "source-missing and existing-field policies."
            ),
        )
    if verb == "RDAHELPER":
        return _suggestion(
            source_line,
            intent="Create RDA content, media, and carrier fields",
            reason=exc.message,
            recommended_operation="rda-classify-material",
            prefilled_params=smith_external_material_operation()["params"],
            cataloger_action=(
                "Open RDA Material Classification and confirm the transparent "
                "Smith replacement for the unsupported external settings."
            ),
        )
    if verb == "SORTBY":
        return _suggestion(
            source_line,
            intent="Sort MARC fields",
            reason=exc.message,
            recommended_operation="sort-fields",
            prefilled_params={},
            cataloger_action=(
                "Open Sort Fields and confirm the requested scope and options."
            ),
        )
    return _suggestion(
        source_line,
        intent="Recreate an external task instruction",
        reason=exc.message,
        recommended_operation="choose-operation",
        prefilled_params={},
        cataloger_action=(
            "Choose the closest structured operation and confirm its parameters."
        ),
    )


def _parse_core(
    source_line: str,
) -> tuple[ExternalInstruction | None, MigrationItem | None]:
    try:
        return parse_instruction(source_line), None
    except ExternalParseError as exc:
        return None, _core_parse_failure(source_line, exc)


def adapt_delete(source_line: str) -> MigrationItem:
    instruction, failure = _parse_core(source_line)
    if failure is not None:
        return failure
    assert instruction is not None
    tag, match = instruction.arguments[:2]
    params = {"tag": tag.strip()} if tag.strip() else {}
    if match:
        return _suggestion(
            source_line,
            intent="Delete fields whose value matches external text",
            reason="matched DELETE behavior is not yet proven for automatic conversion",
            recommended_operation="delete-by-subfield",
            prefilled_params={"tag": tag.strip(), "match": match},
            cataloger_action=(
                "Open Delete Fields Matching Subfield Value and confirm the "
                "external match mode before saving."
            ),
        )
    if not re.fullmatch(r"[0-9Xx]{3}", tag.strip()):
        return _suggestion(
            source_line,
            intent="Delete every field matching a MARC tag pattern",
            reason="DELETE tag must be three digits or use X as a digit wildcard",
            recommended_operation="delete-tag",
            prefilled_params=params,
            cataloger_action="Open Delete Tag and enter a valid exact or wildcard tag.",
        )
    if any(instruction.boolean_flags):
        enabled = ", ".join(
            "flag {0}".format(index)
            for index, value in enumerate(instruction.boolean_flags, start=1)
            if value
        )
        return _suggestion(
            source_line,
            intent="Delete every field matching a MARC tag pattern",
            reason=(
                "DELETE {0} is enabled, and that external policy has no proven "
                "open equivalent".format(enabled)
            ),
            recommended_operation="delete-tag",
            prefilled_params=params,
            cataloger_action=(
                "Open Delete Tag and confirm whether the enabled external "
                "policy can be omitted or recreated separately."
            ),
        )
    return _item(
        source_line,
        status="converted",
        operations=({"kind": "delete-tag", "params": params},),
    )


_ADD_POLICIES = {
    100: "append",
    101: "skip_if_tag_exists",
    108: "skip_if_identical",
}


def adapt_add(source_line: str) -> MigrationItem:
    instruction, failure = _parse_core(source_line)
    if failure is not None:
        return failure
    assert instruction is not None
    tag, field_data, _option, external_condition = instruction.arguments[:4]
    params = _safe_field_params(tag.strip(), field_data)
    if not _is_data_tag(params.get("tag")) or not params.get("subfields"):
        return _suggestion(
            source_line,
            intent="Add a MARC field",
            reason=(
                "ADD must target a data field with lossless indicators and "
                "subfields"
            ),
            recommended_operation="add-field",
            prefilled_params=params,
            cataloger_action=(
                "Open Add Field and correct the field indicators and subfields."
            ),
        )
    option_code = instruction.option_code
    if option_code in _ADD_POLICIES:
        if external_condition:
            return _suggestion(
                source_line,
                intent="Add a MARC field with an external condition",
                reason=(
                    "ADD option {0} does not have a proven conditional form".format(
                        option_code
                    )
                ),
                recommended_operation="add-field",
                prefilled_params=params,
                cataloger_action=(
                    "Open Add Field and confirm both the condition and the "
                    "existing-field policy."
                ),
            )
        params.update({
            "condition": "always",
            "existing_field_action": _ADD_POLICIES[option_code],
        })
    elif option_code == 106:
        try:
            condition = parse_leader_condition(external_condition)
        except ValueError as exc:
            return _suggestion(
                source_line,
                intent="Add a MARC field for records matching a Leader condition",
                reason=str(exc),
                recommended_operation="add-field",
                prefilled_params=params,
                cataloger_action=(
                    "Open Add Field and select the reviewed Leader condition "
                    "that matches the cataloging intent."
                ),
            )
        if condition == "always":
            return _suggestion(
                source_line,
                intent="Add a MARC field conditionally",
                reason="ADD option 106 requires a recognized nonempty Leader condition",
                recommended_operation="add-field",
                prefilled_params=params,
                cataloger_action=(
                    "Open Add Field and select an explicit Leader condition."
                ),
            )
        params.update({
            "condition": condition,
            "existing_field_action": "append",
        })
    else:
        raise AssertionError("typed parser returned an unknown ADD option")
    return _item(
        source_line,
        status="converted",
        operations=({"kind": "add-field", "params": params},),
    )


_BUILD_POLICIES = {
    (False, False, True, False): "skip_if_tag_exists",
    (False, False, False, True): "append",
}


def adapt_build_field(source_line: str) -> MigrationItem:
    instruction, failure = _parse_core(source_line)
    if failure is not None:
        return failure
    assert instruction is not None
    template = instruction.arguments[0]
    params = _safe_build_params(template)
    if not params or not _is_data_tag(params.get("tag")):
        return _suggestion(
            source_line,
            intent="Build a MARC field from source record values",
            reason=(
                "Build Field must target a data field and use supported "
                "lossless source syntax"
            ),
            recommended_operation="build-field",
            prefilled_params=params,
            cataloger_action=(
                "Open Build Field and recreate the template with literal, "
                "control-field, or data-subfield segments."
            ),
        )
    policy = _BUILD_POLICIES.get(instruction.boolean_flags)
    if policy is None:
        return _suggestion(
            source_line,
            intent="Build a MARC field from source record values",
            reason=(
                "Build Field flags {0} have no proven open policy".format(
                    instruction.arguments[1:5]
                )
            ),
            recommended_operation="build-field",
            prefilled_params=params,
            cataloger_action=(
                "Open Build Field and choose explicit missing-source and "
                "existing-field behavior."
            ),
        )
    params.update({
        "condition": "always",
        "existing_field_action": policy,
        "missing_control_action": "skip_field",
    })
    return _item(
        source_line,
        status="converted",
        operations=({"kind": "build-field", "params": params},),
    )


_CORPUS_RDA_SIGNATURE = (
    "1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0"
)


def adapt_rdahelper(source_line: str) -> MigrationItem:
    instruction, failure = _parse_core(source_line)
    if failure is not None:
        return failure
    assert instruction is not None
    if instruction.arguments[0] != _CORPUS_RDA_SIGNATURE:
        positions = instruction.arguments[0].split("|")
        additional = [
            str(index)
            for index, value in enumerate(positions, start=1)
            if index not in {1, 2, 17, 18} and value == "1"
        ]
        detail = (
            "additional enabled RDAHELPER positions: " + ", ".join(additional)
            if additional
            else "RDAHELPER positions differ from the reviewed corpus signature"
        )
        return _suggestion(
            source_line,
            intent="Create RDA fields using explicit open operations",
            reason=detail,
            recommended_operation="rda-classify-material",
            prefilled_params=smith_external_material_operation()["params"],
            cataloger_action=(
                "Open RDA Material Classification and confirm which external "
                "RDA options need separate explicit operations."
            ),
        )
    return _item(
        source_line,
        status="converted",
        operations=(smith_external_material_operation(),),
        disclosure=(
            "Smith open equivalent; not a byte-for-byte external emulation"
        ),
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
    instruction, failure = _parse_core(source_line)
    if failure is not None:
        return failure
    assert instruction is not None
    scope = instruction.arguments[0]
    if scope == "ALL" and instruction.boolean_flags == (True, True):
        return _item(
            source_line,
            status="converted",
            operations=({"kind": "sort-fields", "params": {}},),
        )
    return _suggestion(
        source_line,
        intent="Sort MARC fields using the external scope and options",
        reason=(
            "only SORTBY ALL True True has a proven open equivalent; "
            "received scope {0!r} and flags {1}".format(
                scope, instruction.arguments[1:3]
            )
        ),
        recommended_operation="sort-fields",
        prefilled_params={},
        cataloger_action=(
            "Open Sort Fields and confirm whether sorting all fields matches "
            "the requested external behavior."
        ),
    )


ADAPTER_REGISTRY = {
    "ADD": adapt_add,
    "DELETE": adapt_delete,
    "RDAHELPER": adapt_rdahelper,
    "SUBFIELD_EDIT": adapt_subfield_edit,
    "REPLACE": adapt_replace,
    "SORTBY": adapt_sortby,
    "buildnewfield": adapt_build_field,
}

COMPATIBILITY_ADAPTER_REGISTRY = {
    "subfield-edit-v1": CompatibilityAdapter(
        adapter=adapt_subfield_edit,
        verbs=("SUBFIELD_EDIT",),
        shape_ids=("subfield-edit-literal",),
        fixture_ids=("subfield-edit-literal",),
    ),
    "delete-v1": CompatibilityAdapter(
        adapter=adapt_delete,
        verbs=("DELETE",),
        shape_ids=("delete-exact", "delete-wildcard"),
        fixture_ids=("delete-exact", "delete-wildcard"),
    ),
    "add-v1": CompatibilityAdapter(
        adapter=adapt_add,
        verbs=("ADD",),
        shape_ids=(
            "add-append",
            "add-skip-tag",
            "add-skip-identical",
            "add-leader",
        ),
        fixture_ids=(
            "add-append",
            "add-skip-tag",
            "add-skip-identical",
            "add-leader",
        ),
    ),
    "build-field-v1": CompatibilityAdapter(
        adapter=adapt_build_field,
        verbs=("buildnewfield",),
        shape_ids=("build-if-absent", "build-always"),
        fixture_ids=("build-if-absent", "build-always"),
    ),
    "rda-smith-open-v1": CompatibilityAdapter(
        adapter=adapt_rdahelper,
        verbs=("RDAHELPER",),
        shape_ids=("rda-smith-classify",),
        fixture_ids=("rda-smith-classify",),
    ),
    "sort-all-v1": CompatibilityAdapter(
        adapter=adapt_sortby,
        verbs=("SORTBY",),
        shape_ids=("sort-all",),
        fixture_ids=("sort-all",),
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
    return _suggestion(
        source_line,
        intent="Recreate an unsupported external instruction",
        reason=f"external instruction {verb or '(empty)'} has no proven adapter",
        recommended_operation="choose-operation",
        prefilled_params={},
        cataloger_action=(
            "Choose the closest structured operation and confirm its parameters."
        ),
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
