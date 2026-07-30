from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from marcedit_web.lib import task_builder


SUPPORTED_SCHEMA_VERSION = 1
COMPILER_CONTRACT_VERSION = 1
SERIALIZATION_RUNTIME = "python-3.9"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "native-task-v1.schema.json"
)
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "native-task-compiler-contract-v1.json"
)


class NativeDefinitionError(ValueError):
    pass


class UnsupportedSchemaVersion(NativeDefinitionError):
    pass


class CompilerContractError(RuntimeError):
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
        structured_subfields = [
            [subfield["code"], subfield["segments"]]
            for subfield in step["subfields"]
        ]
        indicators = step["target"]["indicators"]
        return task_builder.Operation(
            kind="build-field",
            params={
                "tag": step["target"]["tag"],
                "ind1": indicators[0],
                "ind2": indicators[1],
                "structured_subfields": structured_subfields,
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_contract_manifest(golden_dir: Path) -> dict[str, Any]:
    snapshots = {}
    for path in sorted(golden_dir.glob("*.json")):
        definition = load_definition_json(path.read_text(encoding="utf-8"))
        compiled = compile_definition(definition)
        snapshots[path.name] = {
            "definition_sha256": _sha256_text(
                canonical_definition_json(definition)
            ),
            "body_sha256": _sha256_text(compiled.body),
            "extra_imports_sha256": _sha256_text("\n".join(compiled.imports)),
        }
    return {
        "native_schema_version": SUPPORTED_SCHEMA_VERSION,
        "compiler_contract_version": COMPILER_CONTRACT_VERSION,
        "serialization_runtime": SERIALIZATION_RUNTIME,
        "golden_snapshots": snapshots,
    }


def canonical_manifest_json(manifest: Mapping[str, Any]) -> str:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_contract_manifest(manifest: Any) -> Mapping[str, Any]:
    if not isinstance(manifest, Mapping):
        raise CompilerContractError("compiler contract manifest must be an object")

    expected_versions = {
        "native_schema_version": SUPPORTED_SCHEMA_VERSION,
        "compiler_contract_version": COMPILER_CONTRACT_VERSION,
        "serialization_runtime": SERIALIZATION_RUNTIME,
    }
    allowed_fields = set(expected_versions) | {"golden_snapshots"}
    unknown_fields = sorted(set(manifest) - allowed_fields)
    if unknown_fields:
        raise CompilerContractError(
            "compiler contract manifest has unknown field "
            f"{unknown_fields[0]}"
        )
    for field, expected in expected_versions.items():
        if field not in manifest:
            raise CompilerContractError(
                f"compiler contract manifest is missing {field}"
            )
        if (
            type(manifest[field]) is not type(expected)
            or manifest[field] != expected
        ):
            raise CompilerContractError(
                f"compiler contract manifest has {field}={manifest[field]!r}; "
                f"expected {expected!r}"
            )

    snapshots = manifest.get("golden_snapshots")
    if not isinstance(snapshots, Mapping):
        raise CompilerContractError(
            "compiler contract manifest golden_snapshots must be an object"
        )
    snapshot_fields = (
        "definition_sha256",
        "body_sha256",
        "extra_imports_sha256",
    )
    for filename, snapshot in snapshots.items():
        if not isinstance(filename, str) or not isinstance(snapshot, Mapping):
            raise CompilerContractError(
                "compiler contract manifest snapshots must map filenames to objects"
            )
        unknown_fields = sorted(set(snapshot) - set(snapshot_fields))
        if unknown_fields:
            raise CompilerContractError(
                f"compiler contract manifest {filename} has unknown field "
                f"{unknown_fields[0]}"
            )
        for field in snapshot_fields:
            digest = snapshot.get(field)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise CompilerContractError(
                    f"compiler contract manifest {filename} has invalid {field}"
                )
    return manifest


def load_contract_manifest() -> Mapping[str, Any]:
    try:
        manifest = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompilerContractError(
            f"cannot load compiler contract manifest: {exc}"
        ) from exc
    return _validate_contract_manifest(manifest)


def verify_contract_manifest(golden_dir: Path) -> None:
    checked_in = load_contract_manifest()
    generated = build_contract_manifest(golden_dir)

    for field in (
        "native_schema_version",
        "compiler_contract_version",
        "serialization_runtime",
    ):
        if checked_in[field] != generated[field]:
            raise CompilerContractError(
                f"compiler contract {field} mismatch: "
                f"checked in {checked_in[field]!r}, generated {generated[field]!r}"
            )

    checked_snapshots = checked_in["golden_snapshots"]
    generated_snapshots = generated["golden_snapshots"]
    for filename in sorted(set(checked_snapshots) | set(generated_snapshots)):
        if filename not in checked_snapshots:
            raise CompilerContractError(
                f"compiler contract missing checked-in snapshot for {filename}"
            )
        if filename not in generated_snapshots:
            raise CompilerContractError(
                f"compiler contract has stale snapshot for {filename}"
            )
        for field in (
            "definition_sha256",
            "body_sha256",
            "extra_imports_sha256",
        ):
            if checked_snapshots[filename][field] != generated_snapshots[filename][
                field
            ]:
                raise CompilerContractError(
                    f"compiler contract {filename} {field} mismatch: "
                    f"checked in {checked_snapshots[filename][field]!r}, "
                    f"generated {generated_snapshots[filename][field]!r}"
                )


def current_compiler_fingerprint() -> str:
    manifest = load_contract_manifest()
    return _sha256_text(canonical_manifest_json(manifest))


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--print-contract", type=Path)
    args = parser.parse_args()
    if args.print_contract is None:
        parser.error("--print-contract GOLDEN_DIR is required")
    print(
        json.dumps(
            build_contract_manifest(args.print_contract),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
