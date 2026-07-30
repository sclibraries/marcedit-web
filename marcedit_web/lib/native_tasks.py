from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from marcedit_web.lib import task_builder


SUPPORTED_SCHEMA_VERSION = 1
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "native-task-v1.schema.json"
)


class NativeDefinitionError(ValueError):
    pass


class UnsupportedSchemaVersion(NativeDefinitionError):
    pass


@dataclass(frozen=True)
class CompiledNativeTask:
    body: str
    imports: tuple[str, ...]


def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeDefinitionError("native task definition must be an object")
    encountered = value.get("schema_version")
    if encountered != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"unsupported native task schema version: encountered "
            f"{encountered!r}; supported version is {SUPPORTED_SCHEMA_VERSION}"
        )
    candidate = copy.deepcopy(dict(value))
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(candidate),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "definition"
        raise NativeDefinitionError(f"{location}: {first.message}")
    ids = [step["id"] for step in candidate["steps"]]
    if len(ids) != len(set(ids)):
        raise NativeDefinitionError("native task step IDs must be unique")
    return candidate


def canonical_definition_json(value: Mapping[str, Any]) -> str:
    valid = validate_definition(value)
    return json.dumps(
        valid,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_definition_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NativeDefinitionError(f"invalid native task JSON: {exc.msg}") from exc
    return validate_definition(value)


def export_definition(value: Mapping[str, Any]) -> bytes:
    return (canonical_definition_json(value) + "\n").encode("utf-8")


def _operation_for_step(step: Mapping[str, Any]) -> task_builder.Operation:
    action = step["action"]
    if action == "delete_tag":
        return task_builder.Operation(
            kind="delete-tag",
            params={"tag": step["target"]["tag"]},
        )
    if action == "sort_fields":
        return task_builder.Operation(kind="sort-fields", params={})
    if action == "build_field":
        subfields = []
        for subfield in step["subfields"]:
            value = "".join(
                segment["value"]
                if segment["type"] == "text"
                else "{" + segment["tag"] + "}"
                for segment in subfield["segments"]
            )
            subfields.append([subfield["code"], value])
        indicators = step["target"]["indicators"]
        return task_builder.Operation(
            kind="build-field",
            params={
                "tag": step["target"]["tag"],
                "ind1": indicators[0],
                "ind2": indicators[1],
                "subfields": subfields,
                "condition": "always",
                "if_absent": step["existing_target"] == "skip",
            },
        )
    raise NativeDefinitionError(f"unsupported native action {action!r}")


def compile_definition(value: Mapping[str, Any]) -> CompiledNativeTask:
    valid = validate_definition(value)
    ops = [_operation_for_step(step) for step in valid["steps"]]
    rendered = task_builder.render_ops_to_python(ops)
    if "# TODO:" in rendered["body"]:
        raise NativeDefinitionError("native task compilation produced unsupported code")
    return CompiledNativeTask(
        body=rendered["body"],
        imports=tuple(rendered["imports"]),
    )
