# TASK-178 Native Task Schema and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, non-executable native task definition, deterministic compiler contract, and fail-closed atomic storage path without changing existing cataloger workflows.

**Architecture:** Canonical JSON validated with JSON Schema is compiled through the existing `task_builder.render_ops_to_python()` bridge. Native definitions, generated body/import snapshots, compiler fingerprints, and task revisions live atomically in the existing `tasks` row; legacy rows keep null native fields and continue through the existing path.

**Tech Stack:** Python 3.9, stdlib dataclasses/JSON/hashlib/SQLite, jsonschema Draft 2020-12, existing task builder and sandbox materialization, pytest, Docker

**Ticket:** [TASK-178](../../../.tickets/TASK-178-native-task-schema-storage.md)

**Design:** [Smith Metadata Studio and Open Task Migration](../specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md)

## Global Constraints

- Native schema version `1` is the only accepted version.
- Unknown versions are refused before editing, compilation, preview, execution, or storage, and errors report encountered and supported versions.
- The canonical definition contains no Python, `custom` action, unresolved review state, hidden positional flags, or unknown no-op behavior.
- TASK-178 initially compiles exactly `delete_tag`, structured `build_field`, and `sort_fields`; later actions require reviewed schema/compiler additions.
- Stable step IDs are unique within a definition and step order is preserved.
- Canonical JSON uses UTF-8, sorted object keys, compact separators, preserved array order, and no trailing newline in SQL.
- Every native save validates and compiles before opening its write transaction.
- The definition, body, imports, compiler fingerprint, and revision change atomically.
- The compiler fingerprint is the SHA-256 of the canonical checked-in compiler-contract manifest.
- A stale fingerprint triggers revision-checked snapshot regeneration and an audit event.
- A current fingerprint with unequal stored snapshots is an integrity failure; stale code never runs.
- Validation, compilation, integrity, or revision-race failures do not modify the stored row.
- Existing task rows are not rewritten during schema migration and retain null native fields.
- Existing legacy task save, materialization, visibility, authorization, and execution behavior remain available.
- A legacy save cannot silently overwrite a native row.
- TASK-178 adds no cataloger-facing native editor, import screen, preview promotion, new authorization, TASK-173 infrastructure, or TASK-175 header behavior.
- Direct dependency additions update `requirements.txt`, `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, and their inventory regression together.
- Python remains `>=3.9,<3.10`; production and deployment identifiers remain `marcedit-web`.

## File Structure

- `marcedit_web/schemas/native-task-v1.schema.json`: published interchange/storage schema.
- `marcedit_web/schemas/native-task-compiler-contract-v1.json`: checked-in golden snapshot hashes and compiler versions.
- `marcedit_web/lib/native_tasks.py`: validation, canonicalization, compilation, manifest verification, and fingerprint API.
- `tests/fixtures/native_tasks/delete-and-sort.json`: ordered deletion/sort golden definition.
- `tests/fixtures/native_tasks/build-field.json`: structured 876 golden definition.
- `marcedit_web/lib/db.py`: schema-v14 nullable native columns and revision migration.
- `marcedit_web/lib/task_db.py`: native save, execution preparation, CAS migration, and legacy protection.
- `tests/test_native_tasks.py`: schema/compiler/round-trip contract.
- `tests/test_native_task_contract.py`: golden-manifest freshness and fingerprint contract.
- `tests/test_native_task_storage.py`: atomic persistence, migration, integrity, audit, and materialization.
- `tests/test_native_task_schema_migration.py`: v13-to-v14 preservation.
- `tests/test_product_identity.py`: direct-dependency notice inventory.

---

### Task 1: Publish and compile native schema version 1

**Files:**
- Create: `marcedit_web/schemas/native-task-v1.schema.json`
- Create: `marcedit_web/lib/native_tasks.py`
- Create: `tests/fixtures/native_tasks/delete-and-sort.json`
- Create: `tests/fixtures/native_tasks/build-field.json`
- Create: `tests/test_native_tasks.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `tests/test_product_identity.py`

**Interfaces:**
- Consumes: `task_builder.Operation` and `task_builder.render_ops_to_python(ops: list[Operation]) -> dict`.
- Produces: `validate_definition(value: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `canonical_definition_json(value: Mapping[str, Any]) -> str`.
- Produces: `load_definition_json(text: str) -> dict[str, Any]`.
- Produces: `export_definition(value: Mapping[str, Any]) -> bytes`.
- Produces: `compile_definition(value: Mapping[str, Any]) -> CompiledNativeTask`.
- Produces: `UnsupportedSchemaVersion`, `NativeDefinitionError`, and immutable `CompiledNativeTask(body: str, imports: tuple[str, ...])`.

- [ ] **Step 1: Add the direct validation dependency contract test**

Extend `tests/test_product_identity.py::test_direct_runtime_dependency_notices_are_present`:

```python
expected = {
    "Streamlit": "Apache-2.0",
    "pymarc": "BSD-2-Clause",
    "streamlit-ace": "MIT",
    "Authlib": "BSD-3-Clause",
    "pytest": "MIT",
    "jsonschema": "MIT",
}
```

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_product_identity.py::test_direct_runtime_dependency_notices_are_present \
    -q
```

Expected: FAIL because `requirements.txt` and notices do not yet declare
`jsonschema`.

- [ ] **Step 2: Declare jsonschema and its notice**

Add the same direct constraint to `requirements.txt` and
`pyproject.toml` runtime dependencies:

```text
jsonschema>=4.23,<5
```

Add this notice row:

```markdown
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | MIT | https://github.com/python-jsonschema/jsonschema |
```

Run the Step 1 test in the existing image. Expected: PASS because jsonschema
4.25.1 is already installed transitively in that image, while the source now
guarantees it directly for rebuilt images.

- [ ] **Step 3: Write failing schema and round-trip tests**

Create `tests/test_native_tasks.py` with tests that assert:

```python
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from marcedit_web.lib import native_tasks


FIXTURES = Path(__file__).parent / "fixtures" / "native_tasks"


def _definition(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_definition_round_trip_preserves_step_order_and_values():
    definition = _definition("delete-and-sort.json")
    exported = native_tasks.export_definition(definition)

    assert exported.endswith(b"\n")
    assert native_tasks.load_definition_json(exported.decode("utf-8")) == definition
    assert [step["id"] for step in definition["steps"]] == [
        "delete-029",
        "sort-fields",
    ]


def test_canonical_json_sorts_keys_but_preserves_arrays():
    definition = _definition("delete-and-sort.json")
    reversed_keys = dict(reversed(list(definition.items())))

    assert native_tasks.canonical_definition_json(reversed_keys) == (
        native_tasks.canonical_definition_json(definition)
    )
    assert json.loads(native_tasks.canonical_definition_json(definition))[
        "steps"
    ] == definition["steps"]


def test_unknown_schema_version_fails_with_encountered_and_supported_values():
    definition = _definition("delete-and-sort.json")
    definition["schema_version"] = 2

    with pytest.raises(
        native_tasks.UnsupportedSchemaVersion,
        match=r"encountered 2; supported version is 1",
    ):
        native_tasks.validate_definition(definition)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda d: d["steps"].append(copy.deepcopy(d["steps"][0])), "step IDs"),
        (lambda d: d["steps"][0].update(action="custom"), "not valid"),
        (lambda d: d["steps"][0].update(code="record.clear\\(\\)"), "code"),
        (lambda d: d.update(review_state="needs_confirmation"), "review_state"),
    ],
)
def test_nonportable_or_ambiguous_definitions_fail_closed(mutation, message):
    definition = _definition("delete-and-sort.json")
    mutation(definition)

    with pytest.raises(native_tasks.NativeDefinitionError, match=message):
        native_tasks.validate_definition(definition)
```

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest tests/test_native_tasks.py -q
```

Expected: FAIL because `native_tasks` and fixtures do not exist.

- [ ] **Step 4: Add exact synthetic golden definitions**

Create `tests/fixtures/native_tasks/delete-and-sort.json`:

```json
{
  "schema_version": 1,
  "name": "delete-vendor-field",
  "description": "Delete 029 fields and restore tag order.",
  "steps": [
    {
      "id": "delete-029",
      "action": "delete_tag",
      "target": {"tag": "029"}
    },
    {
      "id": "sort-fields",
      "action": "sort_fields"
    }
  ]
}
```

Create `tests/fixtures/native_tasks/build-field.json`:

```json
{
  "schema_version": 1,
  "name": "build-holdings-field",
  "description": "Build an 876 from control fields 003 and 001.",
  "steps": [
    {
      "id": "build-876",
      "action": "build_field",
      "target": {
        "tag": "876",
        "indicators": [" ", " "]
      },
      "subfields": [
        {
          "code": "a",
          "segments": [
            {"type": "text", "value": "B("},
            {"type": "control_field", "tag": "003"},
            {"type": "text", "value": ")"},
            {"type": "control_field", "tag": "001"},
            {"type": "text", "value": "-SC"}
          ]
        },
        {
          "code": "l",
          "segments": [
            {"type": "text", "value": "Internet"}
          ]
        }
      ],
      "missing_source": "skip_and_report",
      "existing_target": "append",
      "source": {
        "format": "marcedit-task",
        "line": 7,
        "instruction_sha256": "8c7d6e7a5a3d94fcd03d0c51ef9b2210d21f7296a28e571f8f5ab1a8ab58ef91"
      }
    }
  ]
}
```

These fixtures are synthetic and contain no institutional record or workflow
content.

- [ ] **Step 5: Publish the exact schema boundary**

Create `marcedit_web/schemas/native-task-v1.schema.json` with this complete
Draft 2020-12 contract:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Smith Metadata Studio native task",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "name", "description", "steps"],
  "properties": {
    "schema_version": {"const": 1},
    "name": {
      "type": "string",
      "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
      "maxLength": 128
    },
    "description": {"type": "string", "maxLength": 4096},
    "steps": {
      "type": "array",
      "minItems": 1,
      "items": {
        "oneOf": [
          {"$ref": "#/$defs/delete_tag"},
          {"$ref": "#/$defs/build_field"},
          {"$ref": "#/$defs/sort_fields"}
        ]
      }
    }
  },
  "$defs": {
    "step_id": {
      "type": "string",
      "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
      "maxLength": 128
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["format", "line", "instruction_sha256"],
      "properties": {
        "format": {"const": "marcedit-task"},
        "line": {"type": "integer", "minimum": 1},
        "instruction_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      }
    },
    "delete_tag": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "action", "target"],
      "properties": {
        "id": {"$ref": "#/$defs/step_id"},
        "action": {"const": "delete_tag"},
        "target": {
          "type": "object",
          "additionalProperties": false,
          "required": ["tag"],
          "properties": {
            "tag": {"type": "string", "pattern": "^[0-9X]{3}$"}
          }
        },
        "source": {"$ref": "#/$defs/source"}
      }
    },
    "text_segment": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "value"],
      "properties": {
        "type": {"const": "text"},
        "value": {"type": "string", "maxLength": 4096}
      }
    },
    "control_field_segment": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "tag"],
      "properties": {
        "type": {"const": "control_field"},
        "tag": {"type": "string", "pattern": "^[0-9]{3}$"}
      }
    },
    "subfield": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "segments"],
      "properties": {
        "code": {"type": "string", "pattern": "^[0-9a-z]$"},
        "segments": {
          "type": "array",
          "minItems": 1,
          "items": {
            "oneOf": [
              {"$ref": "#/$defs/text_segment"},
              {"$ref": "#/$defs/control_field_segment"}
            ]
          }
        }
      }
    },
    "build_field": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "action",
        "target",
        "subfields",
        "missing_source",
        "existing_target"
      ],
      "properties": {
        "id": {"$ref": "#/$defs/step_id"},
        "action": {"const": "build_field"},
        "target": {
          "type": "object",
          "additionalProperties": false,
          "required": ["tag", "indicators"],
          "properties": {
            "tag": {"type": "string", "pattern": "^[0-9]{3}$"},
            "indicators": {
              "type": "array",
              "minItems": 2,
              "maxItems": 2,
              "prefixItems": [
                {"type": "string", "minLength": 1, "maxLength": 1},
                {"type": "string", "minLength": 1, "maxLength": 1}
              ],
              "items": false
            }
          }
        },
        "subfields": {
          "type": "array",
          "minItems": 1,
          "items": {"$ref": "#/$defs/subfield"}
        },
        "missing_source": {"const": "skip_and_report"},
        "existing_target": {"enum": ["append", "skip"]},
        "source": {"$ref": "#/$defs/source"}
      }
    },
    "sort_fields": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "action"],
      "properties": {
        "id": {"$ref": "#/$defs/step_id"},
        "action": {"const": "sort_fields"},
        "source": {"$ref": "#/$defs/source"}
      }
    }
  }
}
```

- [ ] **Step 6: Implement validation, canonicalization, and compilation**

Create `marcedit_web/lib/native_tasks.py` with:

```python
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
```

Implement `_operation_for_step(step)` with exact mappings:

```python
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
```

`compile_definition` validates first, maps steps in array order, calls the
existing renderer once, rejects generated bodies containing `# TODO:`, and
returns:

```python
CompiledNativeTask(
    body=rendered["body"],
    imports=tuple(rendered["imports"]),
)
```

- [ ] **Step 7: Add exact compiler behavior tests**

Add tests that require:

```python
def test_delete_and_sort_compile_in_source_order():
    compiled = native_tasks.compile_definition(_definition("delete-and-sort.json"))
    assert compiled.body.index("delete_tags(record, '029')") < compiled.body.index(
        "sort_fields(record)"
    )
    assert compiled.imports == (
        "from marcedit_web.lib.transforms import delete_tags, sort_fields",
    )


def test_structured_build_field_compiles_without_source_text():
    compiled = native_tasks.compile_definition(_definition("build-field.json"))
    assert "_t_003 = control_value(record, '003')" in compiled.body
    assert "_t_001 = control_value(record, '001')" in compiled.body
    assert "'B({003}){001}-SC'" in compiled.body
    assert "marcedit-task" not in compiled.body
    assert "8c7d6e7a" not in compiled.body
```

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest tests/test_native_tasks.py tests/test_product_identity.py -q
```

Expected: all tests pass with zero skips.

- [ ] **Step 8: Commit Task 1**

```bash
git add requirements.txt pyproject.toml THIRD_PARTY_NOTICES.md \
  marcedit_web/schemas/native-task-v1.schema.json \
  marcedit_web/lib/native_tasks.py \
  tests/fixtures/native_tasks tests/test_native_tasks.py \
  tests/test_product_identity.py
git commit -m "feat: add native task schema compiler"
```

---

### Task 2: Add the compiler contract manifest and fingerprint

**Files:**
- Modify: `marcedit_web/lib/native_tasks.py`
- Create: `marcedit_web/schemas/native-task-compiler-contract-v1.json`
- Create: `tests/test_native_task_contract.py`

**Interfaces:**
- Consumes: `compile_definition()` and the two checked-in golden definitions.
- Produces: `build_contract_manifest(golden_dir: Path) -> dict[str, Any]`.
- Produces: `canonical_manifest_json(manifest: Mapping[str, Any]) -> str`.
- Produces: `verify_contract_manifest(golden_dir: Path) -> None`.
- Produces: `current_compiler_fingerprint() -> str`.
- Produces: `CompilerContractError`.

- [ ] **Step 1: Write failing manifest freshness tests**

Create `tests/test_native_task_contract.py`:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from marcedit_web.lib import native_tasks


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "native_tasks"


def test_checked_in_contract_matches_every_golden_definition():
    native_tasks.verify_contract_manifest(GOLDEN_DIR)


def test_fingerprint_is_sha256_of_canonical_manifest_bytes():
    manifest = native_tasks.load_contract_manifest()
    expected = hashlib.sha256(
        native_tasks.canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()

    assert native_tasks.current_compiler_fingerprint() == expected
    assert len(expected) == 64


def test_output_change_requires_manifest_change(monkeypatch):
    original = native_tasks.compile_definition

    def changed(definition):
        compiled = original(definition)
        return native_tasks.CompiledNativeTask(
            body=compiled.body + "\n# changed",
            imports=compiled.imports,
        )

    monkeypatch.setattr(native_tasks, "compile_definition", changed)

    with pytest.raises(native_tasks.CompilerContractError, match="body_sha256"):
        native_tasks.verify_contract_manifest(GOLDEN_DIR)
```

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest tests/test_native_task_contract.py -q
```

Expected: FAIL because manifest APIs do not exist.

- [ ] **Step 2: Implement deterministic manifest construction**

Add constants:

```python
COMPILER_CONTRACT_VERSION = 1
SERIALIZATION_RUNTIME = "python-3.9"
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "native-task-compiler-contract-v1.json"
)
```

Add `CompilerContractError(RuntimeError)`.

`build_contract_manifest` reads every `*.json` in sorted filename order,
loads and compiles each, joins imports with `"\n"` exactly as SQL stores them,
and builds each snapshot entry with:

```python
definition = load_definition_json(path.read_text(encoding="utf-8"))
compiled = compile_definition(definition)
snapshots[path.name] = {
    "definition_sha256": _sha256_text(canonical_definition_json(definition)),
    "body_sha256": _sha256_text(compiled.body),
    "extra_imports_sha256": _sha256_text("\n".join(compiled.imports)),
}
```

Return:

```python
{
    "native_schema_version": SUPPORTED_SCHEMA_VERSION,
    "compiler_contract_version": COMPILER_CONTRACT_VERSION,
    "serialization_runtime": SERIALIZATION_RUNTIME,
    "golden_snapshots": snapshots,
}
```

`_sha256_text` is exactly
`hashlib.sha256(value.encode("utf-8")).hexdigest()`.
`canonical_manifest_json` uses the same sorted, compact,
UTF-8-preserving JSON settings as canonical definitions.

`load_contract_manifest` parses the checked-in file and refuses missing or
wrong top-level version fields. `verify_contract_manifest` compares the
checked-in object to `build_contract_manifest` and reports the first
filename/field mismatch. `current_compiler_fingerprint` verifies the manifest
shape and version fields before hashing its canonical bytes; it does not read
test fixtures or recompile goldens at runtime. The freshness test is the CI
gate that compares generated output to the checked-in manifest.

- [ ] **Step 3: Generate the initial manifest deterministically**

Add a module CLI:

```python
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
```

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m marcedit_web.lib.native_tasks \
    --print-contract tests/fixtures/native_tasks
```

Use the exact deterministic stdout, via `apply_patch`, as
`marcedit_web/schemas/native-task-compiler-contract-v1.json`. Do not type or
guess hashes and do not add a runtime manifest-writing path.

- [ ] **Step 4: Verify and commit Task 2**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_native_tasks.py tests/test_native_task_contract.py -q
```

Expected: all tests pass with zero skips.

Commit:

```bash
git add marcedit_web/lib/native_tasks.py \
  marcedit_web/schemas/native-task-compiler-contract-v1.json \
  tests/test_native_task_contract.py
git commit -m "feat: fingerprint native task compiler contract"
```

---

### Task 3: Migrate the task table and save native rows atomically

**Files:**
- Modify: `marcedit_web/lib/db.py`
- Modify: `marcedit_web/lib/task_db.py`
- Create: `tests/test_native_task_schema_migration.py`
- Create: `tests/test_native_task_storage.py`
- Modify: `tests/test_task_db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces task columns `definition_json TEXT`, `compiler_fingerprint TEXT`, and `revision INTEGER NOT NULL DEFAULT 1`.
- Produces `save_native_task(*, owner: str, definition: Mapping[str, Any], visibility: str = "private", expected_revision: int | None = None) -> dict[str, Any]`.
- Preserves `save_task(...) -> None` for legacy rows.
- Produces `NativeTaskConflict` and `NativeTaskStorageError`.

- [ ] **Step 1: Write the v13-to-v14 preservation test**

Create `tests/test_native_task_schema_migration.py`. Use `sqlite3` to create
the exact pre-v14 `tasks` table from the current `main` schema (through
`updated_at`, with no native columns), insert one legacy task, and create
`_schema_version` containing `13`. Configure the test connection with
`sqlite3.Row`, run `_migrate_to_v14`, and assert:

```python
assert db.SCHEMA_VERSION == 14
assert {
    "definition_json",
    "compiler_fingerprint",
    "revision",
}.issubset(task_columns)
assert row["body"] == "pass"
assert row["extra_imports"] == ""
assert row["definition_json"] is None
assert row["compiler_fingerprint"] is None
assert row["revision"] == 1
```

Call `_migrate_to_v14` twice and require the same columns and values.

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest tests/test_native_task_schema_migration.py -q
```

Expected: FAIL because schema version 14 and migration do not exist.

- [ ] **Step 2: Add the idempotent schema-v14 migration**

Set:

```python
SCHEMA_VERSION = 14
```

Add nullable columns plus revision to the `CREATE TABLE tasks` definition for
new databases. Add:

```python
def _migrate_to_v14(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(tasks)")
    }
    if "definition_json" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN definition_json TEXT")
    if "compiler_fingerprint" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN compiler_fingerprint TEXT")
    if "revision" not in columns:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
        )
```

Call it when `current_version < 14`, after v13. Existing rows are not updated.

Run migration and `tests/test_db.py`; expected: PASS.

- [ ] **Step 3: Write failing atomic native-save tests**

In `tests/test_native_task_storage.py`, load the golden definition and assert:

```python
def test_native_save_stores_canonical_definition_and_snapshots_atomically():
    definition = _definition("delete-and-sort.json")
    row = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        visibility="private",
    )
    compiled = native_tasks.compile_definition(definition)

    assert row["definition_json"] == native_tasks.canonical_definition_json(definition)
    assert row["body"] == compiled.body
    assert row["extra_imports"] == "\n".join(compiled.imports)
    assert row["compiler_fingerprint"] == (
        native_tasks.current_compiler_fingerprint()
    )
    assert row["revision"] == 1


def test_native_update_requires_expected_revision():
    definition = _definition("delete-and-sort.json")
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    definition["description"] = "Changed"

    with pytest.raises(task_db.NativeTaskConflict, match="expected revision"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=definition,
        )

    updated = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        expected_revision=created["revision"],
    )
    assert updated["revision"] == 2
    assert updated["description"] == "Changed"


def test_failed_compile_leaves_existing_native_row_byte_identical(monkeypatch):
    definition = _definition("delete-and-sort.json")
    before = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    monkeypatch.setattr(
        native_tasks,
        "compile_definition",
        lambda value: (_ for _ in ()).throw(
            native_tasks.NativeDefinitionError("compile failed")
        ),
    )

    with pytest.raises(native_tasks.NativeDefinitionError, match="compile failed"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition={**definition, "description": "not stored"},
            expected_revision=before["revision"],
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) == before
```

Also require that `save_task` raises `NativeTaskStorageError` when its target
row has a non-null definition, while ordinary legacy updates still pass.

Expected initial result: FAIL because native storage APIs do not exist.

- [ ] **Step 4: Implement native save and legacy protection**

In `task_db.py`, import `Mapping` and `native_tasks`. Add:

```python
class NativeTaskStorageError(RuntimeError):
    pass


class NativeTaskConflict(NativeTaskStorageError):
    pass
```

`save_native_task` must:

1. validate visibility;
2. call `validate_definition`, `canonical_definition_json`,
   `compile_definition`, and `current_compiler_fingerprint` before
   `db.connect()`;
3. derive row name and description from the canonical definition;
4. store imports as `"\n".join(compiled.imports)`;
5. insert a new row only when none exists and `expected_revision is None`;
6. refuse blind overwrite when a row exists and expected revision is absent;
7. update with:

```sql
UPDATE tasks
SET description = ?,
    body = ?,
    extra_imports = ?,
    definition_json = ?,
    compiler_fingerprint = ?,
    visibility = ?,
    revision = revision + 1,
    updated_at = ?
WHERE owner_email = ? AND name = ? AND revision = ?
```

8. raise `NativeTaskConflict` when rowcount is not one;
9. return the committed row.

For an existing legacy row, a native replacement also requires its current
revision. For an existing native row, `save_task` raises
`NativeTaskStorageError("native tasks must be saved through the native task API")`.
Legacy `save_task` updates increment revision and otherwise retain behavior.
`set_visibility` also increments revision so every row mutation participates
in CAS.

- [ ] **Step 5: Verify storage and legacy regressions**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_native_task_schema_migration.py \
    tests/test_native_task_storage.py \
    tests/test_task_db.py \
    tests/test_db.py -q
```

Expected: all pass with zero skips.

- [ ] **Step 6: Commit Task 3**

```bash
git add marcedit_web/lib/db.py marcedit_web/lib/task_db.py \
  tests/test_native_task_schema_migration.py \
  tests/test_native_task_storage.py tests/test_task_db.py tests/test_db.py
git commit -m "feat: store native tasks atomically"
```

---

### Task 4: Verify, migrate, and materialize execution snapshots

**Files:**
- Modify: `marcedit_web/lib/task_db.py`
- Modify: `marcedit_web/lib/audit.py`
- Modify: `tests/test_native_task_storage.py`
- Modify: `tests/test_task_db.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Produces `prepare_task_for_execution(owner: str, name: str, *, audit_user: str) -> dict[str, Any]`.
- Produces `NativeTaskCompatibilityError` and `NativeTaskIntegrityError`.
- `materialize_to_dir(user, target_dir)` verifies or migrates native rows before writing Python files.
- Emits audit kind `native-task-compiler-migrated` with owner, task name, old fingerprint, and new fingerprint.

- [ ] **Step 1: Write same-fingerprint integrity tests**

Add:

```python
@pytest.mark.parametrize("column", ["body", "extra_imports"])
def test_current_fingerprint_snapshot_mismatch_blocks_without_repair(column):
    definition = _definition("delete-and-sort.json")
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    with db.connect() as conn:
        conn.execute(
            f"UPDATE tasks SET {column} = ? WHERE id = ?",
            ("tampered", created["id"]),
        )
    before = task_db.get_task("alice@example.edu", definition["name"])

    with pytest.raises(task_db.NativeTaskIntegrityError, match=column):
        task_db.prepare_task_for_execution(
            "alice@example.edu",
            definition["name"],
            audit_user="alice@example.edu",
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) == before
```

Expected: FAIL because preparation API does not exist.

- [ ] **Step 2: Write stale-fingerprint migration and audit tests**

Patch `audit.audit_event` with a collector. Store a valid row, manually set
its fingerprint to 64 zeroes and snapshots to old values, then call prepare.
Require:

```python
assert prepared["body"] == native_tasks.compile_definition(definition).body
assert prepared["compiler_fingerprint"] == (
    native_tasks.current_compiler_fingerprint()
)
assert prepared["revision"] == created["revision"] + 1
assert events == [
    (
        "native-task-compiler-migrated",
        {
            "user": "viewer@example.edu",
            "owner": "alice@example.edu",
            "task_name": definition["name"],
            "old_fingerprint": "0" * 64,
            "new_fingerprint": prepared["compiler_fingerprint"],
        },
    )
]
```

Add failure tests:

- stale fingerprint plus compiler failure leaves the row byte-identical;
- a concurrent revision increment during compile makes the CAS update affect
  zero rows, raises `NativeTaskCompatibilityError`, and does not overwrite the
  concurrent row;
- invalid stored canonical JSON blocks without mutation;
- legacy rows return unchanged without invoking the native compiler.

- [ ] **Step 3: Implement fail-closed execution preparation**

`prepare_task_for_execution` loads by owner/name. Missing rows raise
`NativeTaskCompatibilityError`. Legacy rows return directly.

For a native row:

1. parse/validate `definition_json`;
2. compile it and obtain the current fingerprint before a write transaction;
3. when stored fingerprint equals current, compare body and joined imports
   byte for byte and raise `NativeTaskIntegrityError` naming the mismatched
   column;
4. when stale, execute one CAS update matching `id`, `revision`, and the exact
   stored `definition_json`;
5. increment revision and update timestamp in the same statement;
6. if rowcount is not one, raise
   `NativeTaskCompatibilityError("native task changed during compiler migration")`;
7. after commit, call:

```python
audit.audit_event(
    "native-task-compiler-migrated",
    user=audit_user,
    owner=row["owner_email"],
    task_name=row["name"],
    old_fingerprint=row["compiler_fingerprint"],
    new_fingerprint=current_fingerprint,
)
```

8. return the freshly committed row.

Wrap native validation/contract/compile failures as
`NativeTaskCompatibilityError` with the original message and exception
chaining. Do not catch integrity or revision errors into a legacy fallback.

- [ ] **Step 4: Integrate verification into materialization**

In `materialize_to_dir`, replace each native row with:

```python
execution_row = (
    prepare_task_for_execution(
        t["owner_email"],
        t["name"],
        audit_user=user,
    )
    if t.get("definition_json") is not None
    else t
)
```

Serialize only `execution_row`. A failed native row must raise before any file
for that row is written. Existing stale-file cleanup and legacy mtime behavior
remain unchanged.

Add tests proving:

- valid native rows materialize to parseable Python;
- stale native rows migrate before materialization;
- integrity failures create no task file;
- ordinary legacy materialization tests remain unchanged.

Update `audit.py`'s event list with `native-task-compiler-migrated`.

- [ ] **Step 5: Run the complete focused execution boundary**

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_native_tasks.py \
    tests/test_native_task_contract.py \
    tests/test_native_task_schema_migration.py \
    tests/test_native_task_storage.py \
    tests/test_task_db.py \
    tests/test_audit.py -q
```

Expected: all pass with zero skips.

- [ ] **Step 6: Commit Task 4**

```bash
git add marcedit_web/lib/task_db.py marcedit_web/lib/audit.py \
  tests/test_native_task_storage.py tests/test_task_db.py tests/test_audit.py
git commit -m "feat: verify native task execution snapshots"
```

---

### Task 5: Verify the phase and record the TASK-178 checkpoint

**Files:**
- Modify: `.tickets/TASK-178-native-task-schema-storage.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`
- Create: `docs/native-task-format-v1.md`

**Interfaces:**
- Documents the checked-in schema/export contract and legacy boundary.
- Records exact test, migration, fingerprint, audit, Docker, skip, and review evidence.

- [ ] **Step 1: Document the portable format and compatibility boundary**

Create `docs/native-task-format-v1.md` covering:

- canonical file structure and schema path;
- supported schema version `1`;
- supported actions `delete_tag`, `build_field`, and `sort_fields`;
- structured Build Field segments and explicit policies;
- optional privacy-safe provenance;
- export/import canonicalization;
- compiler bridge and fingerprint behavior;
- legacy Python/form-task preservation;
- unknown version/action and integrity failure behavior;
- statement that cataloger UI authoring and external task migration arrive in
  later TASK-174 child tickets.

Use the synthetic 876 example from
`tests/fixtures/native_tasks/build-field.json`; do not include institutional
records or local task corpus content.

- [ ] **Step 2: Build the exact candidate image**

```bash
docker build -t marcedit-web:task-178 .
```

Expected: exit `0`.

Verify dependencies and packaged contracts:

```bash
docker run --rm --network none marcedit-web:task-178 \
  sh -c 'python -c "import jsonschema" &&
         test -f /app/LICENSE &&
         test -f /app/THIRD_PARTY_NOTICES.md &&
         test -f /app/marcedit_web/schemas/native-task-v1.schema.json &&
         test -f /app/marcedit_web/schemas/native-task-compiler-contract-v1.json'
```

Expected: exit `0` with no output.

- [ ] **Step 3: Run focused and complete supported suites**

Focused:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-178 \
  python -m pytest \
    tests/test_native_tasks.py \
    tests/test_native_task_contract.py \
    tests/test_native_task_schema_migration.py \
    tests/test_native_task_storage.py \
    tests/test_task_db.py \
    tests/test_db.py \
    tests/test_audit.py \
    tests/test_product_identity.py -q
```

Expected: all focused tests pass with zero skips.

Complete:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-178 \
  python -m pytest -q
```

Expected: all supported tests pass. Disclose the exact count and every skip;
the known environment-dependent Compose-rendering tests may skip because the
Docker CLI is absent inside the network-disabled image.

- [ ] **Step 4: Audit scope and compatibility**

Run:

```bash
git diff --name-only 4ccc4e1..HEAD
git diff --check 4ccc4e1..HEAD
rg -n "MARCEDIT_WEB_|/marcedit-web/|url_path=\"MarcEditor\"" \
  pyproject.toml README.md marcedit_web deploy scripts
```

Require:

- no `deploy/`, `scripts/`, `.streamlit/`, Compose, systemd, proxy, or worker
  unit changes;
- no cataloger-facing native UI;
- unchanged technical identifiers and authorization functions;
- no tracked path under `MarcEdit Tasks/`;
- only synthetic native fixtures.

- [ ] **Step 5: Record evidence while review is pending**

Update TASK-178 with exact:

- implementation commits;
- schema/compiler supported action list;
- schema-v14 preservation result;
- golden-manifest fingerprint and freshness result;
- atomic save, stale migration, integrity, revision-race, and audit evidence;
- focused/full counts and all skips;
- Docker artifact checks;
- diff/scope audit;
- `Status: In-Progress` pending independent review.

Add an In-Progress Phase 2 checkpoint to TASK-174.

Commit:

```bash
git add docs/native-task-format-v1.md \
  .tickets/TASK-178-native-task-schema-storage.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md
git commit -m "docs: record TASK-178 native storage evidence"
```

- [ ] **Step 6: Independent task and whole-branch review**

Review each implementation task after its commit. Then review the exact
TASK-178 starting commit through HEAD against TASK-178 and the approved
TASK-174 design.

Approval requires:

- zero unresolved Critical or Important findings;
- checked-in schema, manifest, golden fixtures, and documentation agree;
- no native task can run from stale or mismatched snapshots;
- legacy task behavior and authorization remain unchanged;
- every test skip and verification limitation is explicit.

- [ ] **Step 7: Complete TASK-178 after approval**

After review approval, record the exact reviewed range and findings. Set
TASK-178 to `Completed`; keep TASK-174 `In-Progress` for the remaining form,
migration, corpus, and preview phases.

```bash
git add .tickets/TASK-178-native-task-schema-storage.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md
git commit -m "docs: approve TASK-178 native storage phase"
git diff --check 4ccc4e1..HEAD
git status --short
```

Expected: commit succeeds; diff check and tracked status are clean.
