# Structured Add Field and Build Field Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-179](../../../.tickets/TASK-179-structured-add-build-field-authoring.md)

**Design:** [TASK-179 design](../specs/2026-07-30-task-179-structured-add-build-field-authoring-design.md)

**Goal:** Let catalogers author, understand, preview, save, and reopen Add Field and Build Field operations without writing JSON or raw templates.

**Architecture:** Keep the existing form-task `# OP:` storage and compiler path authoritative. Add a small pure `task_authoring` module for normalization, validation, presentation, and preview; add a focused Streamlit renderer for repeatable rows and typed segments; and preserve existing generated-code bytes for already-supported native Build Field tasks. External task conversion remains fail-closed when an ignored flag or unsupported instruction prevents an exact mapping.

**Tech Stack:** Python 3.9, Streamlit 1.x, pymarc 5.x, pytest 8.x, existing `task_builder`, `marcedit_import`, SQLite task storage, and Docker Compose.

## Global Constraints

- Run implementation in an isolated worktree created with `superpowers:using-git-worktrees`; update TASK-179 to `In-Progress` only after the worktree exists.
- Keep `marcedit_web`, `MARCEDIT_WEB_*`, `/marcedit-web/`, service names, paths, database schema, worker, proxy, and deployment files unchanged.
- Keep the existing form-task path authoritative; do not create mixed native/legacy saves or change native schema version 1.
- Do not change existing AI behavior or call a model for validation, preview, routing, or transformation.
- Use only deterministic Python for parsing, validation, summaries, mnemonic output, and preview.
- Preserve the current compiler output for TASK-178's native Build Field fixture; the compiler contract fingerprint must remain unchanged.
- Real files under `MarcEdit Tasks/` and real vendor records remain untracked and must not appear in commits, snapshots, or error fixtures.
- Python syntax must remain compatible with `>=3.9,<3.10`; do not use `slots=True`, `match`, `X | Y` annotations, or other Python 3.10-only syntax.
- Unsupported or ambiguous external instructions must be visible and blocking; never silently discard, guess, or execute them.
- Every test skip must be reported with its exact reason. The local corpus check skips explicitly when `MarcEdit Tasks/` is absent and fails if that directory exists without readable task definitions.
- Use TDD for every behavior change: demonstrate the intended RED before the minimal GREEN.
- Touch only TASK-179 application code, tests, synthetic fixtures, the syntax reference, TASK-179 evidence, and TASK-174/TASK-179 tracking.

---

## File Map

- Create `marcedit_web/lib/task_authoring.py`: pure normalization, row/segment mutation, validation, summaries, mnemonic rendering, and read-only preview.
- Create `marcedit_web/render/task_authoring.py`: Streamlit controls for Add Field rows, Build Field typed segments, and explanation/preview panels.
- Modify `marcedit_web/lib/task_builder.py`: palette schemas and backward-compatible existing-target/missing-source code generation.
- Modify `marcedit_web/render/tasks.py`: delegate Add/Build rendering, validate before save, and obtain at most the first loaded record for preview.
- Modify `marcedit_web/lib/marcedit_import.py`: exact Add classification and unresolved Build Field behavior.
- Create `docs/task-authoring-syntax.md`: supported MARC mnemonic and structured-authoring reference.
- Create `tests/test_task_authoring.py`: pure model, validation, presentation, preview, and compiled-equivalence coverage.
- Create `tests/test_task_authoring_render.py`: focused Streamlit widget contract tests.
- Modify `tests/test_task_builder.py`: palette, code-generation, backward-compatibility, and round-trip tests.
- Modify `tests/test_tasks_workspace_modes.py`: save blocking and first-record editor integration tests.
- Modify `tests/test_marcedit_import.py`: exact/unresolved import classification and no-persist assertions.
- Create `tests/test_task_authoring_corpus.py`: sanitized workflow fixtures and optional local-corpus classification.
- Create `tests/fixtures/task_authoring/smith-core-instance.tasksfile.txt`: sanitized Instance signatures.
- Create `tests/fixtures/task_authoring/smith-core-holdings-items.tasksfile.txt`: sanitized Holdings/Items signatures.
- Create `docs/superpowers/evidence/task-179-cataloger-browser-smoke.md`: exact Docker/browser acceptance evidence.
- Modify `.tickets/TASK-179-structured-add-build-field-authoring.md`: plan link, state, verification, commits, and review.
- Modify `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`: completed Phase 3 checkpoint only after acceptance and review.

---

### Task 1: Structured authoring model and validation

**Files:**
- Create: `marcedit_web/lib/task_authoring.py`
- Create: `tests/test_task_authoring.py`
- Modify: `.tickets/TASK-179-structured-add-build-field-authoring.md`

**Interfaces:**
- Consumes: `task_builder.Operation` dictionaries with `{"kind": str, "params": dict}`.
- Produces: `normalize_operation(op: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `validate_operation(op: Mapping[str, Any]) -> tuple[str, ...]`.
- Produces: `validate_operations(ops: Sequence[Mapping[str, Any]]) -> tuple[str, ...]`.
- Produces: `legacy_value_to_segments(value: str) -> list[dict[str, str]]`.
- Produces: `move_item(items: Sequence[_T], index: int, direction: int) -> list[_T]`.
- Produces: constants `EXISTING_TARGET_POLICIES` and `MISSING_SOURCE_POLICIES`.

- [ ] **Step 1: Create the isolated worktree and mark TASK-179 In-Progress**

Use `superpowers:using-git-worktrees`, create a `task-179` branch/worktree from the approved main commit, then change only the ticket status and plan link:

```markdown
Status: In-Progress

Plan:
- `docs/superpowers/plans/2026-07-30-task-179-structured-add-build-field-authoring.md`
```

Run:

```bash
git status --short
git branch --show-current
```

Expected: the TASK-179 worktree is on its own branch; only the ticket is modified; the user's unrelated main-worktree files are absent from the feature diff.

- [ ] **Step 2: Write failing normalization and validation tests**

Add tests that encode why cataloger input must be lossless and fail closed:

```python
import pytest

from marcedit_web.lib import task_authoring


def test_legacy_build_value_becomes_typed_segments_without_losing_literals():
    assert task_authoring.legacy_value_to_segments(
        "B({003}){001}-SC"
    ) == [
        {"type": "text", "value": "B("},
        {"type": "control_field", "tag": "003"},
        {"type": "text", "value": ")"},
        {"type": "control_field", "tag": "001"},
        {"type": "text", "value": "-SC"},
    ]


def test_literal_braces_are_never_guessed_as_source_references():
    with pytest.raises(
        ValueError,
        match="cannot convert legacy Build Field text losslessly",
    ):
        task_authoring.legacy_value_to_segments("literal {name}")


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"kind": "add-field", "params": {"tag": "87"}}, "three numeric"),
        (
            {
                "kind": "add-field",
                "params": {
                    "tag": "877",
                    "ind1": " ",
                    "ind2": " ",
                    "subfields": [],
                },
            },
            "at least one subfield",
        ),
        (
            {
                "kind": "build-field",
                "params": {
                    "tag": "876",
                    "ind1": " ",
                    "ind2": " ",
                    "structured_subfields": [
                        ["a", [{"type": "control_field", "tag": "245"}]]
                    ],
                },
            },
            "control field 001 through 009",
        ),
    ],
)
def test_invalid_structured_operations_name_the_fault(operation, message):
    assert any(
        message in error
        for error in task_authoring.validate_operation(operation)
    )


def test_existing_if_absent_marker_normalizes_to_skip_without_rewriting_marker():
    normalized = task_authoring.normalize_operation(
        {
            "kind": "build-field",
            "params": {
                "tag": "876",
                "subfields": [["a", "Internet"]],
                "if_absent": True,
            },
        }
    )
    assert normalized["params"]["existing_target"] == "skip"
    assert normalized["params"]["missing_source"] == "skip"
    assert normalized["params"]["structured_subfields"] == [
        ["a", [{"type": "text", "value": "Internet"}]]
    ]


def test_move_item_preserves_order_and_rejects_out_of_range_moves():
    assert task_authoring.move_item(["a", "b", "c"], 1, -1) == [
        "b", "a", "c"
    ]
    assert task_authoring.move_item(["a", "b"], 0, -1) == ["a", "b"]
```

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py
```

Expected: collection fails because `marcedit_web.lib.task_authoring` does not exist.

- [ ] **Step 4: Implement the minimal pure authoring model**

Create `marcedit_web/lib/task_authoring.py` with Python 3.9-compatible types and no Streamlit import:

```python
from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence, TypeVar

from marcedit_web.lib.transforms import is_control_tag


EXISTING_TARGET_POLICIES = ("append", "replace", "skip")
MISSING_SOURCE_POLICIES = ("skip", "fail")
_TAG_RE = re.compile(r"^\d{3}$")
_TOKEN_RE = re.compile(r"\{(\d{3})\}")
_T = TypeVar("_T")


def legacy_value_to_segments(value: str) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    offset = 0
    for match in _TOKEN_RE.finditer(value):
        if match.start() > offset:
            segments.append({"type": "text", "value": value[offset:match.start()]})
        segments.append({"type": "control_field", "tag": match.group(1)})
        offset = match.end()
    if offset < len(value):
        segments.append({"type": "text", "value": value[offset:]})
    consumed = "".join(
        segment["value"]
        if segment["type"] == "text"
        else "{" + segment["tag"] + "}"
        for segment in segments
    )
    if consumed != value or re.search(r"[{}]", _TOKEN_RE.sub("", value)):
        raise ValueError(
            "cannot convert legacy Build Field text losslessly; "
            "review literal braces and source references"
        )
    return segments or [{"type": "text", "value": ""}]


def move_item(items: Sequence[_T], index: int, direction: int) -> list[_T]:
    result = copy.deepcopy(list(items))
    destination = index + direction
    if index < 0 or index >= len(result) or destination < 0 or destination >= len(result):
        return result
    result[index], result[destination] = result[destination], result[index]
    return result
```

Complete normalization and validation with these implementations:

```python
def normalize_operation(op: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(op))
    params = normalized.setdefault("params", {})
    if normalized.get("kind") not in {"add-field", "build-field"}:
        return normalized
    params.setdefault(
        "existing_target",
        "skip" if params.get("if_absent") else "append",
    )
    params.setdefault("missing_source", "skip")
    if normalized["kind"] == "build-field" and "structured_subfields" not in params:
        params["structured_subfields"] = [
            [str(code), legacy_value_to_segments(str(value))]
            for code, value in list(params.get("subfields") or [])
        ]
    return normalized


def validate_operations(
    ops: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    errors = []
    for index, op in enumerate(ops):
        for error in validate_operation(op):
            errors.append("Operation {0}: {1}".format(index + 1, error))
    return tuple(errors)


def _validate_tag(tag: object) -> list[str]:
    value = str(tag or "")
    if not _TAG_RE.fullmatch(value):
        return ["tag must be exactly three numeric characters"]
    if is_control_tag(value):
        return ["Add Field and Build Field targets must be data fields"]
    return []


def _validate_indicator(value: object, label: str) -> list[str]:
    if len(str(value)) != 1:
        return ["{0} must be one character or an explicit blank".format(label)]
    return []


def _validate_code(value: object, label: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9]", str(value or "")):
        return ["{0} must be one lowercase letter or digit".format(label)]
    return []


def validate_operation(op: Mapping[str, Any]) -> tuple[str, ...]:
    kind = str(op.get("kind") or "")
    params = dict(op.get("params") or {})
    if kind == "custom" and "# TODO:" in str(params.get("code") or ""):
        return ("unresolved imported instruction must be recreated",)
    if kind not in {"add-field", "build-field"}:
        return ()
    try:
        normalized = normalize_operation(op)
    except ValueError as exc:
        return (str(exc),)
    params = normalized["params"]
    errors = _validate_tag(params.get("tag"))
    errors.extend(_validate_indicator(params.get("ind1", " "), "indicator 1"))
    errors.extend(_validate_indicator(params.get("ind2", " "), "indicator 2"))
    if params.get("existing_target") not in EXISTING_TARGET_POLICIES:
        errors.append("existing-target policy is not supported")
    if params.get("missing_source") not in MISSING_SOURCE_POLICIES:
        errors.append("missing-source policy is not supported")
    key = "subfields" if kind == "add-field" else "structured_subfields"
    subfields = list(params.get(key) or [])
    if not subfields:
        errors.append("at least one subfield is required")
        return tuple(errors)
    for subfield_index, subfield in enumerate(subfields, start=1):
        if not isinstance(subfield, (list, tuple)) or len(subfield) != 2:
            errors.append(
                "subfield {0} must contain a code and value".format(
                    subfield_index
                )
            )
            continue
        errors.extend(
            _validate_code(
                subfield[0],
                "subfield {0} code".format(subfield_index),
            )
        )
        if kind == "add-field":
            if not isinstance(subfield[1], str):
                errors.append(
                    "subfield {0} value must be text".format(subfield_index)
                )
            continue
        segments = subfield[1]
        if not isinstance(segments, list) or not segments:
            errors.append(
                "subfield {0} needs at least one segment".format(subfield_index)
            )
            continue
        if not any(
            isinstance(segment, Mapping)
            and (
                segment.get("type") == "control_field"
                or (
                    segment.get("type") == "text"
                    and bool(segment.get("value"))
                )
            )
            for segment in segments
        ):
            errors.append(
                "subfield {0} needs at least one output segment".format(
                    subfield_index
                )
            )
        for segment_index, segment in enumerate(segments, start=1):
            segment_type = (
                segment.get("type") if isinstance(segment, Mapping) else None
            )
            if segment_type == "text":
                if not isinstance(segment.get("value"), str):
                    errors.append(
                        "subfield {0} segment {1} literal must be text".format(
                            subfield_index, segment_index
                        )
                    )
            elif segment_type == "control_field":
                tag = str(segment.get("tag") or "")
                if not is_control_tag(tag):
                    errors.append(
                        "subfield {0} segment {1} source must be control "
                        "field 001 through 009".format(
                            subfield_index, segment_index
                        )
                    )
            else:
                errors.append(
                    "subfield {0} segment {1} type is unsupported".format(
                        subfield_index, segment_index
                    )
                )
    return tuple(errors)
```

These functions reject non-numeric tags, control tags used as Add/Build data-field targets, multi-character indicators/codes, empty Add rows, empty Build subfields or segments, unknown segment types, non-control source tags, invalid policies, and any `custom` operation whose code contains the unresolved marker `# TODO:`. They leave unrelated existing operation kinds unchanged.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py
```

Expected: all tests pass with zero skips.

- [ ] **Step 6: Commit Task 1**

```bash
git add .tickets/TASK-179-structured-add-build-field-authoring.md marcedit_web/lib/task_authoring.py tests/test_task_authoring.py
git commit -m "feat: validate structured task authoring"
```

---

### Task 2: Backward-compatible Add/Build compilation policies

**Files:**
- Modify: `marcedit_web/lib/task_builder.py:125-192`
- Modify: `marcedit_web/lib/task_builder.py:421-635`
- Modify: `tests/test_task_builder.py`
- Test: `tests/test_native_task_contract.py`

**Interfaces:**
- Consumes: `task_authoring.normalize_operation`.
- Produces: Add/Build params `existing_target: append|replace|skip`.
- Produces: Build param `missing_source: skip|fail`.
- Preserves: old `if_absent` marker behavior and TASK-178 compiler manifest bytes.

- [ ] **Step 1: Write failing policy and compatibility tests**

Add:

```python
def test_add_field_replace_policy_deletes_target_before_adding():
    out = task_builder.render_ops_to_python([
        Operation(
            kind="add-field",
            params={
                "tag": "877",
                "ind1": " ",
                "ind2": " ",
                "subfields": [["m", "Map"]],
                "existing_target": "replace",
                "condition": "always",
            },
        )
    ])
    assert out["body"].index("delete_tags(record, '877')") < out["body"].index(
        "record.add_ordered_field"
    )
    assert "delete_tags" in out["imports"][0]


def test_build_field_missing_source_fail_is_explicit():
    out = task_builder.render_ops_to_python([
        Operation(
            kind="build-field",
            params={
                "tag": "876",
                "ind1": " ",
                "ind2": " ",
                "structured_subfields": [[
                    "a",
                    [{"type": "control_field", "tag": "001"}],
                ]],
                "existing_target": "append",
                "missing_source": "fail",
                "condition": "always",
            },
        )
    ])
    assert "else:" in out["body"]
    assert "raise ValueError('Build Field requires control field 001')" in out["body"]


def test_old_if_absent_marker_keeps_existing_codegen_shape():
    op = Operation(
        kind="build-field",
        params={
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [[
                "a",
                [
                    {"type": "text", "value": "B("},
                    {"type": "control_field", "tag": "003"},
                    {"type": "text", "value": ")"},
                    {"type": "control_field", "tag": "001"},
                ],
            ]],
            "condition": "always",
            "if_absent": True,
        },
    )
    out = task_builder.render_ops_to_python([op])
    assert "add_field_if_absent" in out["body"]
    assert '"existing_target"' not in out["body"]
```

Record the current compiler fingerprint before editing:

```bash
docker compose run --rm marcedit-web python -c "from marcedit_web.lib.native_tasks import current_compiler_fingerprint; print(current_compiler_fingerprint())"
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_builder.py -k "replace_policy or missing_source_fail or old_if_absent"
```

Expected: replace-policy and fail-policy assertions fail; old compatibility remains green.

- [ ] **Step 3: Implement minimal policy code without changing old output**

Import `task_authoring` and normalize only for policy lookup:

```python
normalized = task_authoring.normalize_operation(op.to_dict())
policy_params = normalized["params"]
existing_target = policy_params["existing_target"]
missing_source = policy_params["missing_source"]
```

Keep the existing append and old `if_absent` branches byte-for-byte. Add only:

```python
if existing_target == "replace":
    add_lines = [f"delete_tags(record, {lit(tag)})", add_stmt]
    imports.add("delete_tags")
elif existing_target == "skip":
    add_lines = [f"if not record.get_fields({lit(tag)}):", f"    {add_stmt}"]
else:
    add_lines = [add_stmt]
```

For backward compatibility, if the original params contain `if_absent` and do not contain `existing_target`, retain the existing `add_field_if_absent` output rather than emitting the new tag-level skip branch.

For missing source failure, append an `else` aligned with the existing token guard:

```python
missing = ", ".join(tokens)
body_lines.extend([
    "else:",
    f"    raise ValueError({lit('Build Field requires control field ' + missing)})",
])
```

Update the palette:

```python
{
    "name": "existing_target",
    "label": "When this tag already exists",
    "type": "select",
    "options": [
        {"value": "append", "label": "Add another field"},
        {"value": "replace", "label": "Replace existing fields with this tag"},
        {"value": "skip", "label": "Leave the record unchanged"},
    ],
    "default": "append",
}
```

Build Field also receives:

```python
{
    "name": "missing_source",
    "label": "When a source control field is missing",
    "type": "select",
    "options": [
        {"value": "skip", "label": "Skip this record and report it"},
        {"value": "fail", "label": "Record a task error"},
    ],
    "default": "skip",
}
```

Do not remove `if_absent` reading from `_render_one`; old saved tasks and TASK-178 depend on it.

- [ ] **Step 4: Run focused and compiler-contract tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_builder.py tests/test_native_tasks.py tests/test_native_task_contract.py
docker compose run --rm marcedit-web python -c "from marcedit_web.lib.native_tasks import current_compiler_fingerprint; print(current_compiler_fingerprint())"
```

Expected: all tests pass with zero skips, and the fingerprint is exactly the value recorded in Step 1. If it differs, stop: do not update the manifest in TASK-179; restore the old generated shape.

- [ ] **Step 5: Commit Task 2**

```bash
git add marcedit_web/lib/task_builder.py tests/test_task_builder.py
git commit -m "feat: add explicit field construction policies"
```

---

### Task 3: Plain-language explanation, mnemonic output, and safe preview

**Files:**
- Modify: `marcedit_web/lib/task_authoring.py`
- Modify: `tests/test_task_authoring.py`
- Test: `tests/test_sandbox.py`

**Interfaces:**
- Produces: `AuthoringPreview` dataclass with `status`, `mnemonic`, and `message`.
- Produces: `describe_operation(op: Mapping[str, Any]) -> str`.
- Produces: `render_mnemonic(op: Mapping[str, Any], record: Optional[Record] = None) -> str`.
- Produces: `token_annotations(op: Mapping[str, Any]) -> tuple[str, ...]`.
- Produces: `preview_operation(op: Mapping[str, Any], record: Optional[Record]) -> AuthoringPreview`.

- [ ] **Step 1: Write failing explanation and preview tests**

Add the local fixtures before the tests:

```python
from pymarc import Field, Record


def _source_record():
    record = Record()
    record.add_field(Field(tag="001", data="SYNTHETIC12345"))
    record.add_field(Field(tag="003", data="NhCcYBP"))
    return record


def smith_035_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "035",
            "ind1": "9",
            "ind2": " ",
            "structured_subfields": [[
                "a",
                [
                    {"type": "text", "value": "("},
                    {"type": "control_field", "tag": "003"},
                    {"type": "text", "value": ")"},
                    {"type": "control_field", "tag": "001"},
                ],
            ]],
            "existing_target": "append",
            "missing_source": "skip",
            "condition": "always",
        },
    }


def smith_876_operation(missing_source="skip"):
    return {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "B("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                        {"type": "text", "value": "-SC"},
                    ],
                ],
                ["l", [{"type": "text", "value": "Internet"}]],
            ],
            "existing_target": "append",
            "missing_source": missing_source,
            "condition": "always",
        },
    }


def build_operation_with_text(value):
    operation = smith_035_operation()
    operation["params"]["structured_subfields"] = [
        ["a", [{"type": "text", "value": value}]]
    ]
    return operation


def test_035_explanation_and_resolved_preview_agree():
    operation = smith_035_operation()
    assert task_authoring.describe_operation(operation) == (
        "Add a 035 field with indicator 1 “9”, a blank indicator 2, "
        "and subfield a built from 003 and 001."
    )
    preview = task_authoring.preview_operation(operation, _source_record())
    assert preview.status == "ready"
    assert preview.mnemonic == "=035  9\\$a(NhCcYBP)SYNTHETIC12345"


def test_876_preview_keeps_two_subfields_in_order():
    preview = task_authoring.preview_operation(
        smith_876_operation(), _source_record()
    )
    assert preview.mnemonic == (
        "=876  \\\\$aB(NhCcYBP)SYNTHETIC12345-SC$lInternet"
    )


def test_missing_source_preview_obeys_skip_and_fail_policies():
    record = Record()
    record.add_field(Field(tag="001", data="123"))
    skipped = task_authoring.preview_operation(
        smith_876_operation(missing_source="skip"), record
    )
    failed = task_authoring.preview_operation(
        smith_876_operation(missing_source="fail"), record
    )
    assert skipped.status == "skipped"
    assert skipped.message == "Missing required control field 003."
    assert failed.status == "error"
    assert failed.message == "Missing required control field 003."


def test_preview_never_mutates_source_record():
    record = _source_record()
    before = record.as_marc()
    task_authoring.preview_operation(smith_035_operation(), record)
    assert record.as_marc() == before


def test_literal_braces_render_as_literals_in_structured_preview():
    operation = build_operation_with_text("{local}")
    assert "$a{local}" in task_authoring.preview_operation(
        operation, _source_record()
    ).mnemonic
```

Add an equivalence test that renders the operation through `task_builder` and runs the compiled body through the existing sandbox. This test encodes why UI preview and execution cannot drift:

```python
from pymarc import MARCReader

from marcedit_web.lib import sandbox, task_builder
from marcedit_web.lib.task_builder import Operation


def test_876_preview_matches_compiled_sandbox_output():
    record = _source_record()
    operation = smith_876_operation()
    rendered = task_builder.render_ops_to_python([
        Operation.from_dict(operation)
    ])
    result = sandbox.run_tasks_subprocess(
        [
            sandbox.TaskSpec(
                name="preview-equivalence",
                body=rendered["body"],
                imports=rendered["imports"],
            )
        ],
        record.as_marc(),
    )
    assert result.returncode == 0
    assert result.errors == []
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert output["876"].get_subfields("a") == [
        "B(NhCcYBP)SYNTHETIC12345-SC"
    ]
    assert output["876"].get_subfields("l") == ["Internet"]
    assert task_authoring.preview_operation(
        operation, record
    ).mnemonic == (
        "=876  \\\\$aB(NhCcYBP)SYNTHETIC12345-SC$lInternet"
    )
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py -k "explanation or preview or braces or equivalence"
```

Expected: failures for missing presentation and preview interfaces.

- [ ] **Step 3: Implement deterministic presentation**

Add the required imports and data type:

```python
from dataclasses import dataclass
from typing import Optional

from pymarc import Record


@dataclass(frozen=True)
class AuthoringPreview:
    status: str
    mnemonic: str
    message: str


def _display_indicator(value: str) -> str:
    return "\\" if value == " " else value


def _resolve_segments(
    segments: Sequence[Mapping[str, str]],
    record: Optional[Record],
) -> tuple[str, tuple[str, ...]]:
    parts = []
    missing = []
    for segment in segments:
        if segment["type"] == "text":
            parts.append(segment["value"])
            continue
        if record is None:
            parts.append("{" + segment["tag"] + "}")
            continue
        field = record.get(segment["tag"]) if record is not None else None
        if field is None:
            missing.append(segment["tag"])
        else:
            parts.append(str(field.data))
    return "".join(parts), tuple(dict.fromkeys(missing))


def _join_words(values: Sequence[str]) -> str:
    if len(values) < 2:
        return "".join(values)
    if len(values) == 2:
        return " and ".join(values)
    return ", ".join(values[:-1]) + ", and " + values[-1]


def describe_operation(op: Mapping[str, Any]) -> str:
    normalized = normalize_operation(op)
    params = normalized["params"]
    tag = params["tag"]
    ind1 = (
        "a blank indicator 1"
        if params.get("ind1", " ") == " "
        else "indicator 1 “{0}”".format(params["ind1"])
    )
    ind2 = (
        "a blank indicator 2"
        if params.get("ind2", " ") == " "
        else "indicator 2 “{0}”".format(params["ind2"])
    )
    key = (
        "subfields"
        if normalized["kind"] == "add-field"
        else "structured_subfields"
    )
    codes = [str(code) for code, _value in params[key]]
    label = "subfield" if len(codes) == 1 else "subfields"
    description = "Add a {0} field with {1}, {2}, and {3} {4}".format(
        tag, ind1, ind2, label, _join_words(codes)
    )
    if normalized["kind"] == "build-field":
        sources = []
        for _code, segments in params["structured_subfields"]:
            for segment in segments:
                if (
                    segment["type"] == "control_field"
                    and segment["tag"] not in sources
                ):
                    sources.append(segment["tag"])
        if sources:
            description += " built from {0}".format(_join_words(sources))
    return description + "."


def render_mnemonic(
    op: Mapping[str, Any],
    record: Optional[Record] = None,
) -> str:
    normalized = normalize_operation(op)
    params = normalized["params"]
    if normalized["kind"] == "add-field":
        resolved_subfields = [
            (str(code), str(value))
            for code, value in params["subfields"]
        ]
    else:
        resolved_subfields = [
            (str(code), _resolve_segments(segments, record)[0])
            for code, segments in params["structured_subfields"]
        ]
    prefix = "={0}  {1}{2}".format(
        params["tag"],
        _display_indicator(params.get("ind1", " ")),
        _display_indicator(params.get("ind2", " ")),
    )
    subfield_text = "".join(
        "${0}{1}".format(code, value)
        for code, value in resolved_subfields
    )
    return prefix + subfield_text


def token_annotations(op: Mapping[str, Any]) -> tuple[str, ...]:
    normalized = normalize_operation(op)
    params = normalized["params"]
    annotations = [
        "={0}: target MARC tag.".format(params["tag"]),
        "{0}{1}: indicator 1 and indicator 2; backslash means blank.".format(
            _display_indicator(params.get("ind1", " ")),
            _display_indicator(params.get("ind2", " ")),
        ),
    ]
    key = (
        "subfields"
        if normalized["kind"] == "add-field"
        else "structured_subfields"
    )
    for code, value in params[key]:
        annotations.append("${0}: start subfield {0}.".format(code))
        if normalized["kind"] == "add-field":
            annotations.append("{0}: literal subfield text.".format(value))
            continue
        for segment in value:
            if segment["type"] == "text":
                annotations.append(
                    "{0}: literal text.".format(segment["value"])
                )
            else:
                annotations.append(
                    "{{{0}}}: value from control field {0}.".format(
                        segment["tag"]
                    )
                )
    return tuple(annotations)
```

Implement preview status selection:

```python
def preview_operation(
    op: Mapping[str, Any],
    record: Optional[Record],
) -> AuthoringPreview:
    errors = validate_operation(op)
    if errors:
        return AuthoringPreview("error", "", "; ".join(errors))
    normalized = normalize_operation(op)
    unresolved = render_mnemonic(normalized)
    if record is None:
        return AuthoringPreview(
            "no-file",
            unresolved,
            "Load a MARC file to resolve source control fields.",
        )
    candidate = copy.deepcopy(record)
    params = normalized["params"]
    missing = []
    if normalized["kind"] == "build-field":
        for _code, segments in params["structured_subfields"]:
            for segment in segments:
                if (
                    segment["type"] == "control_field"
                    and candidate.get(segment["tag"]) is None
                    and segment["tag"] not in missing
                ):
                    missing.append(segment["tag"])
    if missing:
        status = "error" if params["missing_source"] == "fail" else "skipped"
        return AuthoringPreview(
            status,
            unresolved,
            "Missing required control field {0}.".format(", ".join(missing)),
        )
    if (
        params["existing_target"] == "skip"
        and candidate.get_fields(params["tag"])
    ):
        return AuthoringPreview(
            "skipped",
            unresolved,
            "Target field {0} already exists.".format(params["tag"]),
        )
    return AuthoringPreview(
        "ready",
        render_mnemonic(normalized, candidate),
        "Preview resolved from the first loaded record.",
    )
```

The preview deep-copies the input record before inspection, resolves only typed Add/Build values, and returns `no-file`, `ready`, `skipped`, or `error`. It does not mutate the original record or import Streamlit, session state, task storage, sandbox, or an AI module.

`token_annotations` must identify the target tag, both indicators, each subfield, every literal segment, and every source-control-field segment in display order.

- [ ] **Step 4: Run preview and sandbox-equivalence tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py tests/test_sandbox.py -k "authoring or preview or task_030_new_ops_combined_smoke"
```

Expected: all selected tests pass with zero skips.

- [ ] **Step 5: Commit Task 3**

```bash
git add marcedit_web/lib/task_authoring.py tests/test_task_authoring.py
git commit -m "feat: preview structured MARC field construction"
```

---

### Task 4: Repeatable Streamlit row and segment controls

**Files:**
- Create: `marcedit_web/render/task_authoring.py`
- Create: `tests/test_task_authoring_render.py`
- Modify: `marcedit_web/render/tasks.py:919-1132`
- Modify: `tests/test_tasks_workspace_modes.py`

**Interfaces:**
- Consumes: mutable Add/Build `params`, operation index, optional first `Record`, and pure functions from `lib.task_authoring`.
- Produces: `render_add_field_params(params: dict, *, key_prefix: str) -> None`.
- Produces: `render_build_field_params(params: dict, *, key_prefix: str) -> None`.
- Produces: `render_operation_explanation(op: Mapping[str, Any], record: Optional[Record]) -> None`.

- [ ] **Step 1: Write failing row/segment renderer tests**

Build a focused fake Streamlit object that records widget labels and button presses. Define `_source_record`, `smith_035_operation`, and `smith_876_operation` locally in this test module using the exact dictionaries from Task 3 so this file does not depend on another test module. Add:

```python
def test_add_field_uses_rows_instead_of_json_textarea(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = {
        "tag": "877",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["m", "Map"]],
        "existing_target": "append",
        "condition": "always",
    }
    renderer.render_add_field_params(params, key_prefix="op_0")
    assert "Subfield code" in fake.text_input_labels
    assert "Subfield value" in fake.text_input_labels
    assert fake.text_area_labels == []


def test_add_subfield_button_appends_one_blank_row(monkeypatch):
    fake = FakeStreamlit(pressed={"op_0_add_subfield"})
    renderer = _renderer(monkeypatch, fake)
    params = {"subfields": [["a", "first"]]}
    renderer.render_add_field_params(params, key_prefix="op_0")
    assert params["subfields"] == [["a", "first"], ["", ""]]
    assert fake.rerun_count == 1


def test_build_field_renders_typed_text_and_control_segments(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = smith_876_operation()["params"]
    renderer.render_build_field_params(params, key_prefix="op_0")
    assert "Segment type" in fake.selectbox_labels
    assert "Literal text" in fake.text_input_labels
    assert "Source control field" in fake.text_input_labels


def test_operation_panel_shows_plain_mnemonic_annotations_and_preview(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    renderer.render_operation_explanation(
        smith_035_operation(), _source_record()
    )
    assert any("Add a 035 field" in text for text in fake.captions)
    assert any("=035" in text for text in fake.code_blocks)
    assert any("control field 003" in text for text in fake.markdown_blocks)
```

Add an integration test in `test_tasks_workspace_modes.py` proving `_render_form_editor` asks `session.current_store().get(0)` at most once and delegates only Add/Build operations to the focused renderer.

- [ ] **Step 2: Run renderer tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring_render.py tests/test_tasks_workspace_modes.py -k "field or operation_panel or first_record"
```

Expected: import or attribute failures because the renderer does not exist.

- [ ] **Step 3: Implement focused Streamlit renderer**

Create `marcedit_web/render/task_authoring.py`. Use explicit labels and existing `st.columns`, `st.button`, `st.text_input`, `st.selectbox`, `st.caption`, `st.code`, and `st.expander` APIs. Mutate the passed params only after collecting the full row/segment value.

Use key helpers:

```python
def _key(prefix: str, *parts: object) -> str:
    return "_".join([prefix] + [str(part) for part in parts])
```

Use one small button helper:

```python
def _move_or_remove(
    items: list,
    index: int,
    *,
    key_prefix: str,
) -> tuple[list, bool]:
    if st.button("↑", key=_key(key_prefix, index, "up"), disabled=index == 0):
        return task_authoring.move_item(items, index, -1), True
    if st.button(
        "↓",
        key=_key(key_prefix, index, "down"),
        disabled=index == len(items) - 1,
    ):
        return task_authoring.move_item(items, index, 1), True
    if st.button("Remove", key=_key(key_prefix, index, "remove")):
        return items[:index] + items[index + 1:], True
    return items, False
```

For Build Field, each subfield row owns an ordered `segments` list. Segment type options are exactly `text` and `control_field`; changing type replaces the row with the corresponding empty shape:

```python
{"type": "text", "value": ""}
{"type": "control_field", "tag": ""}
```

The explanation panel renders:

```python
st.caption(task_authoring.describe_operation(op))
st.code(task_authoring.render_mnemonic(op), language="text")
with st.expander("What this MARC syntax means"):
    for annotation in task_authoring.token_annotations(op):
        st.markdown("- " + annotation)
preview = task_authoring.preview_operation(op, record)
if preview.status == "ready":
    st.code(preview.mnemonic, language="text")
elif preview.status == "error":
    st.error(preview.message)
else:
    st.info(preview.message)
```

- [ ] **Step 4: Delegate from the existing Tasks form**

In `render/tasks.py`, import the new render module with an unambiguous alias:

```python
from marcedit_web.render import task_authoring as task_authoring_render
```

Obtain the preview record once before the operation loop:

```python
store = session.current_store()
preview_record = store.get(0) if store is not None and store.count() else None
```

For Add/Build:

```python
if op["kind"] == "add-field":
    task_authoring_render.render_add_field_params(
        params, key_prefix=f"op_{i}"
    )
elif op["kind"] == "build-field":
    task_authoring_render.render_build_field_params(
        params, key_prefix=f"op_{i}"
    )
else:
    for param in palette_entry["params"]:
        _render_param_input(
            param,
            params,
            key_prefix=f"op_{i}",
            is_admin=is_admin,
        )

if op["kind"] in {"add-field", "build-field"}:
    task_authoring_render.render_operation_explanation(
        op, preview_record
    )
```

Do not call the generic JSON `subfields` textarea for Add/Build. Leave it available for unrelated old operation parameter types until those receive their own tickets.

- [ ] **Step 5: Run renderer and workspace tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring_render.py tests/test_tasks_workspace_modes.py tests/test_task_builder.py
```

Expected: all tests pass with zero skips.

- [ ] **Step 6: Commit Task 4**

```bash
git add marcedit_web/render/task_authoring.py marcedit_web/render/tasks.py tests/test_task_authoring_render.py tests/test_tasks_workspace_modes.py
git commit -m "feat: add guided Add and Build Field controls"
```

---

### Task 5: Save validation and fail-closed external imports

**Files:**
- Modify: `marcedit_web/render/tasks.py:453-540`
- Modify: `marcedit_web/render/tasks.py:1134-1215`
- Modify: `marcedit_web/lib/marcedit_import.py:145-240`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `tests/test_marcedit_import.py`

**Interfaces:**
- Consumes: `task_authoring.validate_operations`.
- Produces: exact Add conversion only when ignored external columns are empty and the condition is known.
- Preserves: unresolved external line text in the import result and displays it before refusing persistence.

- [ ] **Step 1: Write failing save and import tests**

Add:

```python
def test_save_blocks_invalid_structured_field_before_sql(monkeypatch, tmp_path):
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = [{
        "kind": "add-field",
        "params": {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [],
            "existing_target": "append",
            "condition": "always",
        },
    }]
    tasks_render._save_callback(tmp_path)
    assert saved == []
    assert "Operation 1" in fake_st.session_state[tasks_render.K_SAVE_ERROR]
    assert "at least one subfield" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_save_blocks_unresolved_import_marker(monkeypatch, tmp_path):
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = [{
        "kind": "custom",
        "params": {"code": "# TODO: unresolved external Build Field flags"},
    }]
    tasks_render._save_callback(tmp_path)
    assert saved == []
    assert "unresolved imported instruction" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]
```

Add importer tests:

```python
def test_add_with_empty_priority_and_known_condition_is_exact():
    src = "ADD\t877\t\\\\\\\\$mMap\t\t/=LDR.{8}[e,f].+/\n"
    result = marcedit_import.convert_tasksfile_text(
        src, name="map", description_fallback=""
    )
    assert result.unsupported == []
    assert "# OP: add-field" in result.body


def test_add_with_unmapped_numeric_priority_remains_blocking():
    src = "ADD\t877\t\\\\\\\\$mMap\t106\t/=LDR.{8}[e,f].+/\n"
    result = marcedit_import.convert_tasksfile_text(
        src, name="map", description_fallback=""
    )
    assert result.unsupported == [src.rstrip()]
    assert "unresolved ADD option" in result.body


def test_buildnewfield_flags_remain_visible_and_unresolved():
    line = (
        "buildnewfield\t=876  \\\\\\\\$aB({003}){001}-SC$lInternet"
        "\tFalse\tFalse\tTrue\tFalse"
    )
    result = marcedit_import.convert_tasksfile_text(
        line + "\n", name="holdings", description_fallback=""
    )
    assert result.unsupported == [line]
    assert line.split("\t")[1] in result.body
```

Add UI tests proving `_do_marcedit_import` does not call `task_db.save_task` for a conversion with `unsupported`, displays a bounded list of unresolved lines, and still saves an exact entry from the same archive.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_marcedit_import.py tests/test_tasks_workspace_modes.py -k "structured or unresolved or priority or buildnewfield"
```

Expected: current broad Add conversion and direct import persistence fail the new assertions.

- [ ] **Step 3: Validate before rendering or persistence**

In `_save_callback`, before `render_ops_to_python`:

```python
raw_ops = st.session_state.get(K_EDITOR_OPS, [])
validation_errors = task_authoring.validate_operations(raw_ops)
if validation_errors:
    raise ValueError("\n".join(validation_errors))
ops = [Operation.from_dict(op) for op in raw_ops]
```

Do not mutate session state during validation. A failed save must leave the existing SQL row, task registry, and materialized task file unchanged.

- [ ] **Step 4: Tighten external classification**

In `_emit_add`, treat a non-empty priority column or any non-empty unrecognized trailing column as unresolved:

```python
priority = parts[3].strip() if len(parts) > 3 else ""
unknown_tail = [value for value in parts[5:] if value.strip()]
if priority or unknown_tail:
    return HandlerEmission(
        code=(
            "# TODO: unresolved ADD option(s); priority={0!r}, "
            "trailing={1!r} — recreate with structured Add Field"
        ).format(priority, unknown_tail),
    )
```

Keep `_emit_buildnewfield` unresolved because the observed Boolean order is not proven. Its message must name the template and tell the cataloger to recreate it with structured Build Field controls.

In `_do_marcedit_import`, use one helper:

```python
def _save_exact_conversion(user: str, conv: ConversionResult) -> bool:
    if conv.unsupported:
        st.warning(
            "Not imported: this task contains unresolved external "
            "instructions. Recreate the listed Add/Build steps with "
            "structured controls."
        )
        for line in conv.unsupported[:20]:
            st.code(line, language="text")
        if len(conv.unsupported) > 20:
            st.caption(
                "{0} additional unresolved lines omitted.".format(
                    len(conv.unsupported) - 20
                )
            )
        return False
    task_db.save_task(
        owner=user,
        name=conv.name,
        description=conv.description or "",
        body=conv.body,
        extra_imports=conv.imports,
        visibility="private",
    )
    return True
```

Use it for text imports and each archive entry. Archive reporting distinguishes exact imports from unresolved entries; no unresolved conversion is persisted or executed.

- [ ] **Step 5: Run import, save, and regression tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_marcedit_import.py tests/test_tasks_workspace_modes.py tests/test_task_import_traversal.py tests/test_tasks_export.py
```

Expected: all tests pass with zero skips.

- [ ] **Step 6: Commit Task 5**

```bash
git add marcedit_web/lib/marcedit_import.py marcedit_web/render/tasks.py tests/test_marcedit_import.py tests/test_tasks_workspace_modes.py
git commit -m "fix: block ambiguous external task instructions"
```

---

### Task 6: Supported syntax reference and Smith CORE fixtures

**Files:**
- Create: `docs/task-authoring-syntax.md`
- Create: `tests/fixtures/task_authoring/smith-core-instance.tasksfile.txt`
- Create: `tests/fixtures/task_authoring/smith-core-holdings-items.tasksfile.txt`
- Create: `tests/test_task_authoring_corpus.py`
- Modify: `tests/test_task_authoring.py`

**Interfaces:**
- Consumes: `task_authoring.render_mnemonic`, `marcedit_import.convert_tasksfile_text`, and the two synthetic fixture paths.
- Produces: user-facing documentation limited to supported behavior.
- Produces: optional local classification report with explicit absent-corpus skip.

- [ ] **Step 1: Write failing fixture and documentation-freshness tests**

Define `smith_035_operation` and `smith_876_operation` locally using the exact synthetic dictionaries from Task 3, then add:

```python
FIXTURES = Path(__file__).parent / "fixtures" / "task_authoring"
REFERENCE = Path(__file__).parents[1] / "docs" / "task-authoring-syntax.md"


def test_smith_core_instance_fixture_contains_035_and_visible_rda_gap():
    text = (FIXTURES / "smith-core-instance.tasksfile.txt").read_text()
    assert "=035  9\\\\$a({003}){001}" in text
    assert "RDAHELPER" in text


def test_holdings_fixture_contains_876_and_add_examples():
    text = (
        FIXTURES / "smith-core-holdings-items.tasksfile.txt"
    ).read_text()
    assert "=876  \\\\\\\\$aB({003}){001}-SC$lInternet" in text
    assert "ADD\t852" in text
    assert "ADD\t877" in text


def test_reference_examples_match_executable_mnemonics():
    reference = REFERENCE.read_text()
    assert task_authoring.render_mnemonic(
        smith_035_operation()
    ) in reference
    assert task_authoring.render_mnemonic(
        smith_876_operation()
    ) in reference
    assert "RDAHELPER" in reference
    assert "not supported" in reference.lower()
```

Add the local-only supplement:

```python
CORPUS = Path(__file__).parents[1] / "MarcEdit Tasks"


def test_local_task_corpus_add_and_build_signatures_are_classified():
    if not CORPUS.exists():
        pytest.skip(
            "institutional MarcEdit Tasks corpus is unavailable; "
            "synthetic fixtures remain authoritative"
        )
    task_files = sorted(CORPUS.rglob("*.txt"))
    if not task_files:
        pytest.fail(
            "MarcEdit Tasks exists but contains no readable .txt definitions"
        )
    outcomes = []
    for task_file in task_files:
        for line in task_file.read_text(errors="replace").splitlines():
            if line.startswith("ADD\t") or line.startswith("buildnewfield\t"):
                result = marcedit_import.convert_tasksfile_text(
                    line + "\n",
                    name="classification",
                    description_fallback="",
                )
                outcomes.append(
                    "unresolved" if result.unsupported else "exact"
                )
    assert outcomes, "corpus has no Add Field or Build Field signatures"
    assert set(outcomes) <= {"exact", "unresolved"}
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring_corpus.py tests/test_task_authoring.py -k "reference or fixture or corpus"
```

Expected: fixture/reference tests fail because files do not exist. The corpus test either reports its explicit skip or classifies the local corpus if deliberately mounted.

- [ ] **Step 3: Add sanitized synthetic fixtures**

The Instance fixture contains only synthetic identifiers and the relevant signatures:

```text
#DESCRIPTION#Sanitized Smith CORE Instance authoring fixture
buildnewfield	=035  9\$a({003}){001}	False	False	True	False
RDAHELPER
```

The Holdings/Items fixture contains:

```text
#DESCRIPTION#Sanitized Smith CORE Holdings and Items authoring fixture
ADD	852	8\$hOnline$tOther scheme$lSCINT
buildnewfield	=876  \\$aB({003}){001}-SC$lInternet	False	False	True	False
ADD	877	\\$mMap
```

These files intentionally retain unresolved external flags so classification tests prove the importer does not guess. They contain no real record content, GUID, staff identity, vendor URL, barcode, job identifier, or production path.

- [ ] **Step 4: Write the running syntax reference**

Create `docs/task-authoring-syntax.md` with these sections:

```markdown
# Smith Metadata Studio Task Authoring Syntax

## What the structured editor stores
## MARC mnemonic anatomy
## Add Field
## Build Field
## Literal text
## Source control fields
## Existing-target choices
## Missing-source choices
## Supported examples
### Build 035 from 003 and 001
### Build 876 from literals, 003, and 001
### Add 852 and 877
## Save, reopen, and preview
## External task imports
## Unsupported and deferred syntax
```

Explain the exact mnemonic tokens:

```text
=876  \\$aB({003}){001}-SC$lInternet
```

- `=876`: target MARC tag.
- `\\`: two blank indicators.
- `$a`: start subfield a.
- `B(`, `)`, and `-SC`: literal text.
- `{003}` and `{001}`: values read from those control fields.
- `$lInternet`: subfield l with literal value `Internet`.

State prominently that the structured editor stores typed segments, not an executable raw template; the mnemonic is a transparent technical representation. Document only behavior covered by committed tests. Mark RDAHELPER, unknown external flags, arbitrary `.mrk` regex, and undocumented numeric/pipe-delimited options as not supported.

- [ ] **Step 5: Run fixture, docs, import, and pure-model tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py tests/test_task_authoring_corpus.py tests/test_marcedit_import.py
```

Expected: all authoritative synthetic tests pass. Report the local-corpus result exactly: either pass with classification counts or one explicit unavailable-corpus skip.

- [ ] **Step 6: Audit tracked fixture privacy**

Run:

```bash
git status --short
git diff -- tests/fixtures/task_authoring docs/task-authoring-syntax.md
git ls-files "MarcEdit Tasks"
rg -n "roconnell|smith\\.edu|libtools2|6015796|TFeba9780020306634" tests/fixtures/task_authoring docs/task-authoring-syntax.md
```

Expected: `git ls-files "MarcEdit Tasks"` prints nothing; the sensitive-pattern scan prints nothing. The synthetic examples use visibly fake values such as `12345`.

- [ ] **Step 7: Commit Task 6**

```bash
git add docs/task-authoring-syntax.md tests/fixtures/task_authoring tests/test_task_authoring.py tests/test_task_authoring_corpus.py
git commit -m "docs: add structured task authoring reference"
```

---

### Task 7: Integrated Docker and cataloger acceptance

**Files:**
- Create: `docs/superpowers/evidence/task-179-cataloger-browser-smoke.md`
- Modify: `.tickets/TASK-179-structured-add-build-field-authoring.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`

**Interfaces:**
- Consumes: the exact committed TASK-179 candidate.
- Produces: reproducible automated and browser evidence.
- Produces: completed ticket state only after review has no unresolved Critical or Important findings.

- [ ] **Step 1: Run static and focused verification**

Run:

```bash
python3 -m py_compile marcedit_web/lib/task_authoring.py marcedit_web/lib/task_builder.py marcedit_web/lib/marcedit_import.py marcedit_web/render/task_authoring.py marcedit_web/render/tasks.py
git diff --check main...HEAD
docker compose run --rm marcedit-web pytest -q tests/test_task_authoring.py tests/test_task_authoring_render.py tests/test_task_authoring_corpus.py tests/test_task_builder.py tests/test_marcedit_import.py tests/test_tasks_workspace_modes.py tests/test_native_tasks.py tests/test_native_task_contract.py tests/test_task_import_traversal.py
```

Expected: static checks pass; focused tests pass; every skip is listed and explained. The compiler fingerprint still equals the pre-Task-2 value.

- [ ] **Step 2: Build the exact candidate and run the full suite**

Run:

```bash
docker compose build marcedit-web
docker compose run --rm marcedit-web pytest -ra
```

Expected: the complete Python 3.9 suite passes. Record exact passed, failed, skipped, warning, duration, and image digest values; do not summarize a suite containing skips as simply “all tests pass.”

- [ ] **Step 3: Start the local application for browser acceptance**

Run:

```bash
docker compose up -d marcedit-web
docker compose ps
```

Expected: `marcedit-web` reaches healthy/running state at `http://localhost:8501`.

- [ ] **Step 4: Perform the cataloger walkthrough**

Use `browser-use` or the in-app browser-control skill because this step requires interacting with the local Streamlit UI. Record:

1. Open **Tasks → Build & import → New task**.
2. Add **Build field from template**.
3. Enter 035, indicators `9` and blank, subfield `a`, and the five ordered segments for `({003}){001}`.
4. Confirm the plain-language statement, technical mnemonic, token explanation, and resolved synthetic preview agree.
5. Save, close, reopen, and confirm row/segment order and values are unchanged.
6. Build 876 with `$aB({003}){001}-SC$lInternet`.
7. Add representative 852 and 877 fields using rows without entering JSON.
8. Attempt an ambiguous external Build Field import and confirm the original line is visible, the uncertainty is explained, and no executable task is saved.
9. Confirm no AI prompt, generated prose, or AI network request appears in this workflow.

Take an accessibility snapshot and screenshot showing the structured 876 operation with mnemonic and preview. Do not include a real vendor record, staff identity, or production URL.

- [ ] **Step 5: Record browser evidence**

Write `docs/superpowers/evidence/task-179-cataloger-browser-smoke.md`:

```markdown
# TASK-179 Cataloger Browser Smoke Evidence

- Candidate commit:
- Docker image digest:
- Browser URL:
- Synthetic fixture:
- Add Field rows:
- 035 Build Field:
- 876 Build Field:
- Save/reopen:
- Missing-source behavior:
- Ambiguous import refusal:
- AI/network boundary:
- Accessibility snapshot:
- Screenshot:
- Deviations:
```

Replace every label with observed evidence. “Deviations” must say `None` or list each deviation and its disposition.

- [ ] **Step 6: Request independent review**

Use `superpowers:requesting-code-review` against the exact `main...HEAD` range. The review prompt must check:

- spec and ticket coverage;
- no JSON/raw-template requirement in normal Add/Build entry;
- preview/execution equivalence and non-mutation;
- lossless save/reopen;
- exact import classification and blocking;
- TASK-178 fingerprint stability;
- Python 3.9 compatibility;
- institutional-corpus privacy;
- no AI, native schema, database, deployment, service, worker, proxy, or ITS changes; and
- no unresolved Critical or Important findings.

Fix findings through new RED/GREEN cycles and rerun affected focused plus full verification.

- [ ] **Step 7: Complete tracking only after verification and review**

Update TASK-179 by copying the exact commit hashes and command output produced in the preceding steps. Use complete numeric counts and the unchanged fingerprint value; do not use qualitative shorthand:

```markdown
Status: Completed

Final Evidence:
- Implementation commits: list every TASK-179 commit hash and subject.
- Focused Docker: record exact passed, failed, skipped, warning, and duration values plus each skip reason.
- Full Docker: record exact passed, failed, skipped, warning, and duration values plus each skip reason.
- Compiler fingerprint: record the exact unchanged SHA-256 value.
- Browser acceptance: `docs/superpowers/evidence/task-179-cataloger-browser-smoke.md`
- Independent review: record the exact reviewed range and disposition of every finding.
```

Add a concise TASK-174 Phase 3 checkpoint. Do not mark TASK-180, TASK-181, TASK-182, or parent TASK-174 Completed.

- [ ] **Step 8: Commit final evidence**

```bash
git add .tickets/TASK-179-structured-add-build-field-authoring.md .tickets/TASK-174-smith-metadata-studio-open-task-migration.md docs/superpowers/evidence/task-179-cataloger-browser-smoke.md
git commit -m "docs: complete TASK-179 structured authoring"
```

- [ ] **Step 9: Run final exact-range checks**

Run:

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
git diff --name-only main...HEAD
git ls-files "MarcEdit Tasks"
```

Expected: clean TASK-179 worktree; only planned files changed; no institutional corpus tracked; all implementation and evidence commits visible.

---

## Execution Success Criteria

Execution is complete only when:

1. TASK-179 is `Completed`, with every implementation commit and verification result recorded.
2. Add Field uses repeatable ordered rows and normal entry contains no JSON textarea.
3. Build Field uses typed literal/control-field segments and normal entry contains no raw template textarea.
4. The 035 and 876 examples resolve correctly, retain literal text, and preserve subfield order.
5. Plain language, technical mnemonic, annotations, and first-record preview agree.
6. Preview is deterministic and proven not to mutate source data or create output.
7. Save/reopen is lossless for rows, segments, policies, types, and order.
8. Invalid structured input and unresolved external instructions block persistence before SQL mutation.
9. Ambiguous external Add/Build flags remain visible and are not guessed or executed.
10. The TASK-178 compiler fingerprint is unchanged.
11. The supported syntax reference is synchronized with executable synthetic fixtures.
12. The local corpus remains untracked, and its optional check either passes with classifications or skips loudly because the corpus is unavailable.
13. Focused and full Python 3.9 Docker verification completes with every skip disclosed.
14. Cataloger browser acceptance passes on synthetic data.
15. Independent review reports no unresolved Critical or Important findings.
